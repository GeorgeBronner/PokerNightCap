// Main game state and rendering logic

const SUIT_SYMBOL = { clubs: '♣', diamonds: '♦', hearts: '♥', spades: '♠' };
const SUIT_COLOR = { clubs: 'black', diamonds: 'red', hearts: 'red', spades: 'black' };

const RANK_VALUE = { 2: 2, 3: 3, 4: 4, 5: 5, 6: 6, 7: 7, 8: 8, 9: 9, 10: 10, J: 11, Q: 12, K: 13, A: 14 };
// Index = hand category; names match the backend evaluator's hand_name values.
const HAND_NAMES = ['High Card', 'Pair', 'Two Pair', 'Three of a Kind', 'Straight', 'Flush', 'Full House', 'Four of a Kind', 'Straight Flush', 'Royal Flush'];

// Name of the best 5-card poker hand makeable from 5-7 cards.
function bestHandName(cards) {
  let best = -1;
  for (const combo of _combinations(cards, 5)) {
    const rank = _rank5(combo);
    if (rank > best) best = rank;
  }
  return HAND_NAMES[best] || null;
}

function _combinations(arr, k) {
  if (arr.length < k) return [];
  if (arr.length === k) return [arr];
  const out = [];
  const idx = Array.from({ length: k }, (_, i) => i);
  while (true) {
    out.push(idx.map(i => arr[i]));
    let i = k - 1;
    while (i >= 0 && idx[i] === arr.length - k + i) i--;
    if (i < 0) break;
    idx[i]++;
    for (let j = i + 1; j < k; j++) idx[j] = idx[j - 1] + 1;
  }
  return out;
}

function _rank5(cards) {
  const vals = cards.map(c => RANK_VALUE[c.rank]).sort((a, b) => b - a);
  const isFlush = cards.every(c => c.suit === cards[0].suit);
  const uniq = [...new Set(vals)];
  let straightHigh = 0;
  if (uniq.length === 5) {
    if (uniq[0] - uniq[4] === 4) straightHigh = uniq[0];
    else if (uniq[0] === 14 && uniq[1] === 5 && uniq[4] === 2) straightHigh = 5; // wheel
  }
  const counts = {};
  vals.forEach(v => { counts[v] = (counts[v] || 0) + 1; });
  const sizes = Object.values(counts).sort((a, b) => b - a);
  if (straightHigh && isFlush) return straightHigh === 14 ? 9 : 8;
  if (sizes[0] === 4) return 7;
  if (sizes[0] === 3 && sizes[1] === 2) return 6;
  if (isFlush) return 5;
  if (straightHigh) return 4;
  if (sizes[0] === 3) return 3;
  if (sizes[0] === 2 && sizes[1] === 2) return 2;
  if (sizes[0] === 2) return 1;
  return 0;
}

const AVATAR_COLORS = ['#d4af37', '#7fb3d5', '#c39bd3', '#7dcea0', '#f0b27a', '#e07b7b', '#85c1e9', '#f7dc6f', '#a3e4d7', '#d98880'];

function initials(name) {
  const parts = String(name).trim().split(/\s+/);
  const chars = parts.length > 1 ? parts[0][0] + parts[1][0] : String(name).slice(0, 2);
  return chars.toUpperCase();
}

// Seat positions evenly spaced around the oval table, computed on an ellipse.
// Index 0 = bottom center (the viewing player), going clockwise. Supports 10 seats.
// Each entry also carries the spot on the felt where that seat's bet chips go.
const TOTAL_SEATS = 10;
const SEAT_POSITIONS = (() => {
  const cx = 50, cy = 50, rx = 47, ry = 48;  // pods straddle the rim; table-wrap padding gives them room
  const betRx = rx * 0.56, betRy = ry * 0.52;
  const btnRx = rx * 0.70, btnRy = ry * 0.66;  // dealer button: just outside the bet spots
  const seats = [];
  for (let i = 0; i < TOTAL_SEATS; i++) {
    const theta = ((90 + i * (360 / TOTAL_SEATS)) * Math.PI) / 180;
    // Nudge the dealer button clockwise so it doesn't sit on the bet chips
    const btnTheta = ((90 + i * (360 / TOTAL_SEATS) + 13) * Math.PI) / 180;
    seats.push({
      left: `${(cx + rx * Math.cos(theta)).toFixed(2)}%`,
      top: `${(cy + ry * Math.sin(theta)).toFixed(2)}%`,
      betLeft: `${(cx + betRx * Math.cos(theta)).toFixed(2)}%`,
      betTop: `${(cy + betRy * Math.sin(theta)).toFixed(2)}%`,
      btnLeft: `${(cx + btnRx * Math.cos(btnTheta)).toFixed(2)}%`,
      btnTop: `${(cy + btnRy * Math.sin(btnTheta)).toFixed(2)}%`,
    });
  }
  return seats;
})();

class GameState {
  constructor(socket, myPlayerId) {
    this.socket = socket;
    this.myPlayerId = myPlayerId;
    this.state = null;
    this.turnTimerInterval = null;
    this._turnDeadline = null;
    this._nextHandTimer = null;
    this._chat = null;
    this._myHoleCards = null;
    this._winnerIds = new Set();
    this._handLabels = {};
    this._dirtySettingsInputs = new Set();
    this._settingsInputsWired = false;
  }

  setChat(chatBox) { this._chat = chatBox; }

  // ---- Server message handlers ----

  handleRoomState(payload) {
    // The server includes dealer_seat (null before the first hand); fall back
    // to the remembered value for older payloads that omit it
    const dealerSeat = this.state?.dealer_seat;
    this.state = payload;
    if (payload.dealer_seat == null && dealerSeat != null) this.state.dealer_seat = dealerSeat;
    this.renderAll();
  }

  handlePlayerJoined(payload) {
    if (!this.state) return;
    const existing = this.state.players.findIndex(p => p.id === payload.player.id);
    if (existing === -1) {
      this.state.players.push(payload.player);
      this._log(`${payload.player.display_name} joins the table with $${(payload.player.chips ?? 0).toLocaleString()}.`);
    } else {
      // Already seated — this is a reconnect/refresh; update silently
      this.state.players[existing] = payload.player;
    }
    this.renderPlayers();
  }

  handlePlayerLeft(payload) {
    if (!this.state) return;
    this.state.players = this.state.players.filter(p => p.id !== payload.player_id);
    if (payload.new_admin_id) this.state.admin_id = payload.new_admin_id;
    this.renderPlayers();
    this.renderAdminPanel();
  }

  handleAdminChanged(payload) {
    if (!this.state) return;
    this.state.admin_id = payload.new_admin_id;
    this.renderAdminPanel();
    const p = this.state.players.find(p => p.id === payload.new_admin_id);
    this._log(`${p ? p.display_name : 'Someone'} is now the admin.`);
  }

  handleHandStarted(payload) {
    if (!this.state) return;
    this._myHoleCards = null;
    this._turnDeadline = null;
    this._winnerIds = new Set();
    this._handLabels = {};
    const inHand = payload.player_ids || [];
    Object.assign(this.state, payload);
    this.state.stage = 'pre_flop';
    this.state.community_cards = [];
    this.state.pot_total = 0;
    this.state.current_player_id = null;
    // Reset player states; mark who was dealt into this hand (for face-down cards)
    this.state.players.forEach(p => {
      p.is_folded = false;
      p.is_all_in = false;
      p.current_bet = 0;
      p.has_cards = inHand.includes(p.id);
    });
    this.renderAll();
    this._log(`--- Hand #${payload.hand_number} started ---`);
    document.getElementById('start-game-btn')?.classList.add('hidden');
    document.getElementById('next-hand-btn')?.classList.add('hidden');
    if (this._nextHandTimer) { clearTimeout(this._nextHandTimer); this._nextHandTimer = null; }
  }

  handleHoleCardsDealt(payload) {
    this._myHoleCards = payload.cards;
    this._renderMyHoleCards();
    const el = document.getElementById(`seat-cards-${this.myPlayerId}`);
    if (el) Animations.dealHoleCards([el]);
  }

  handleActionRequired(payload) {
    if (payload.player_id !== this.myPlayerId) return;
    if (this.state) this.state.current_player_id = this.myPlayerId;
    this._turnDeadline = payload.deadline;
    this._showActionPanel(payload);
    this.renderPlayers();
    this._startTurnTimer(payload.deadline);
  }

  handleTurnChanged(payload) {
    if (!this.state) return;
    this.state.current_player_id = payload.player_id;
    this._turnDeadline = payload.deadline;
    // Hide action panel if it's not our turn
    if (payload.player_id !== this.myPlayerId) {
      this._hideActionPanel();
    }
    this.renderPlayers();
    this._startTurnTimer(payload.deadline);
  }

  handlePlayerActed(payload) {
    if (!this.state) return;
    const p = this.state.players.find(p => p.id === payload.player_id);
    if (p) {
      if (payload.action === 'fold') p.is_folded = true;
      if (payload.action === 'all_in') p.is_all_in = true;
      p.current_bet = (p.current_bet || 0) + payload.amount;
    }
    this.state.pot_total = payload.pot_total;
    this.renderPlayers();
    this.renderPot();
    const name = p ? p.display_name : payload.player_id;
    const amtStr = payload.amount > 0 ? ` ${payload.amount}` : '';
    this._log(`${name} ${payload.action}s${amtStr}.`);

    if (payload.player_id === this.myPlayerId) {
      this._hideActionPanel();
      this._stopTurnTimer();
    }
  }

  handleStageChanged(payload) {
    if (!this.state) return;
    this.state.stage = payload.stage;
    this.state.community_cards = payload.community_cards;
    this.state.players.forEach(p => { p.current_bet = 0; });
    this.renderCommunityCards();
    this.renderPlayers();
    this.renderStageIndicator();
    const stageNames = { flop: 'Flop', turn: 'Turn', river: 'River' };
    this._log(`--- ${stageNames[payload.stage] || payload.stage} ---`);
  }

  handleHandResult(payload) {
    this._stopTurnTimer();
    this._hideActionPanel();
    if (this.state) {
      // player_hands is empty when the hand ended by folds; the table keeps
      // showing the street it ended on until the next hand starts.
      const wentToShowdown = payload.player_hands && Object.keys(payload.player_hands).length > 0;
      if (wentToShowdown) this.state.stage = 'showdown';
      this.state.current_player_id = null;
      this.state.players.forEach(p => { p.has_cards = false; });
    }
    this.renderStageIndicator();

    this._winnerIds = new Set(payload.winners.map(w => w.player_id));
    payload.winners.forEach(w => {
      const p = this.state?.players.find(p => p.id === w.player_id);
      const name = p ? p.display_name : w.player_id;
      this._log(`${name} wins ${w.amount} chips!`);
    });

    if (payload.player_hands) {
      Object.entries(payload.player_hands).forEach(([pid, hand]) => {
        const p = this.state?.players.find(p => p.id === pid);
        if (p) {
          this._handLabels[pid] = hand.hand_name;
          this._log(`${p.display_name}: ${hand.hand_name}`);
        }
      });
    }

    // Update chip counts
    if (payload.chips_delta && this.state) {
      this.state.players.forEach(p => {
        if (payload.chips_delta[p.id] !== undefined) {
          p.chips = (p.chips || 0) + payload.chips_delta[p.id];
        }
      });
    }

    // Show winner glow and revealed hand names right away
    this.renderPlayers();

    setTimeout(() => {
      this.renderPlayers();
      this.renderPot();
    }, 3000);

    // After 5s, reveal the "Deal Next Hand" button to everyone (anyone can click).
    if (this._nextHandTimer) clearTimeout(this._nextHandTimer);
    this._nextHandTimer = setTimeout(() => {
      document.getElementById('next-hand-btn')?.classList.remove('hidden');
    }, 5000);
  }

  handleChipsUpdated(payload) {
    if (!this.state) return;
    const p = this.state.players.find(p => p.id === payload.player_id);
    if (p) {
      p.chips = payload.new_total;
      this.renderPlayers();
    }
  }

  handlePlayerKicked(payload) {
    if (payload.player_id === this.myPlayerId) {
      alert('You have been kicked from the room.');
      window.location.href = '/';
      return;
    }
    if (this.state) {
      this.state.players = this.state.players.filter(p => p.id !== payload.player_id);
      this.renderPlayers();
    }
  }

  handleSettingsUpdated(payload) {
    if (!this.state) return;
    Object.assign(this.state.settings, payload);
    // Server confirmed new values; discard any unsaved edits and resync
    this._dirtySettingsInputs.clear();
    this._syncSettingsInputs();
  }

  handleError(payload) {
    console.error('Server error:', payload.code, payload.message);
    showToast(payload.message, 'error');
  }

  // ---- Rendering ----

  renderAll() {
    this.renderPlayers();
    this.renderCommunityCards();
    this.renderPot();
    this.renderAdminPanel();
    this.renderStageIndicator();
  }

  renderPlayers() {
    const tableEl = document.getElementById('table');
    if (!tableEl || !this.state) return;

    // Clear existing seat, bet, and dealer-button elements
    tableEl.querySelectorAll('.seat, .bet-on-felt, .dealer-btn-felt').forEach(el => el.remove());

    const me = this.state.players.find(p => p.id === this.myPlayerId);
    const myRawSeat = me ? me.seat_position : 0;
    const totalSeats = SEAT_POSITIONS.length;

    this.state.players.forEach((player, i) => {
      const seatEl = document.createElement('div');
      // Rotate so the viewing player always appears at position 0 (bottom center)
      const rotatedSeat = (player.seat_position - myRawSeat + totalSeats) % totalSeats;
      const pos = SEAT_POSITIONS[rotatedSeat] || SEAT_POSITIONS[i % totalSeats];
      seatEl.className = 'seat';
      seatEl.id = `seat-${player.id}`;
      seatEl.style.left = pos.left;
      seatEl.style.top = pos.top;

      const isMe = player.id === this.myPlayerId;
      const isCurrent = player.id === this.state.current_player_id;
      const isAdmin = player.id === this.state.admin_id;
      const isDealer = this.state.dealer_seat != null && player.seat_position === this.state.dealer_seat
        && this.state.stage && this.state.stage !== 'waiting';

      if (player.is_folded) seatEl.classList.add('seat-folded');
      if (isCurrent) seatEl.classList.add('seat-active');
      if (!player.is_connected) seatEl.classList.add('seat-disconnected');
      if (this._winnerIds.has(player.id)) seatEl.classList.add('seat-winner');

      const badges = [];
      if (isAdmin) badges.push('<span class="badge badge-admin">A</span>');
      if (isMe) badges.push('<span class="badge badge-me">YOU</span>');

      // Face-down cards for opponents still in the hand (own cards rendered separately).
      const showBacks = !isMe && player.has_cards && !player.is_folded;
      const backsHtml = showBacks ? '<div class="card card-back"></div><div class="card card-back"></div>' : '';

      // Visible countdown on the seat whose turn it is.
      const showTimer = isCurrent && this._turnDeadline && this._inPlay();
      const timerHtml = showTimer
        ? `<div class="seat-timer" id="seat-timer">${this._remainingSeconds()}s</div>`
        : '';

      let status = '';
      if (player.is_folded) status = '<div class="seat-status">Folded</div>';
      else if (player.is_all_in) status = '<div class="seat-status seat-allin">All-in</div>';

      const handName = this._handLabels[player.id] || (isMe ? this._liveHandName() : null);
      const cardsHtml = `<div class="seat-cards" id="seat-cards-${player.id}">${backsHtml}</div>`;
      const podHtml = `
        <div class="pod">
          <div class="avatar" style="background:${AVATAR_COLORS[player.seat_position % AVATAR_COLORS.length]}">${escapeHtml(initials(player.display_name))}</div>
          <div class="pod-info">
            <div class="seat-name">${escapeHtml(player.display_name)}${badges.join('')}</div>
            <div class="seat-chips">$${(player.chips ?? 0).toLocaleString()}</div>
            ${status}
          </div>
          ${isDealer ? '<div class="dealer-btn">D</div>' : ''}
          ${timerHtml}
        </div>`;
      const labelHtml = handName ? `<div class="hand-label">${escapeHtml(handName)}</div>` : '';

      // Hole cards sit on whichever side of the pod faces the table center
      const topHalf = parseFloat(pos.top) < 50;
      seatEl.innerHTML = topHalf ? podHtml + cardsHtml + labelHtml : labelHtml + cardsHtml + podHtml;
      tableEl.appendChild(seatEl);

      // Dealer button on the felt next to the seat; rotates clockwise each hand
      if (isDealer) {
        const btnEl = document.createElement('div');
        btnEl.className = 'dealer-btn-felt';
        btnEl.style.left = pos.btnLeft;
        btnEl.style.top = pos.btnTop;
        btnEl.title = 'Dealer button';
        btnEl.textContent = 'D';
        tableEl.appendChild(btnEl);
      }

      // Bet chips on the felt, between the seat and the pot
      if (player.current_bet > 0 && !player.is_folded) {
        const betEl = document.createElement('div');
        betEl.className = 'bet-on-felt';
        betEl.style.left = pos.betLeft;
        betEl.style.top = pos.betTop;
        const bb = this.state.settings?.big_blind || 20;
        const chipCount = player.current_bet <= bb ? 1 : player.current_bet <= bb * 5 ? 2 : 3;
        const colors = ['', 'c-blue', 'c-gold'];
        const chips = Array.from({ length: chipCount }, (_, c) => `<span class="chip ${colors[c]}"></span>`).join('');
        betEl.innerHTML = `<span class="chipstack">${chips}</span><span class="bet-amt">$${player.current_bet.toLocaleString()}</span>`;
        tableEl.appendChild(betEl);
      }
    });

    // Re-apply hole cards after the seat elements are recreated
    this._renderMyHoleCards();
  }

  // Live strength of my hand, shown over my cards from the flop onward.
  _liveHandName() {
    if (!this._myHoleCards) return null;
    const community = this.state?.community_cards || [];
    if (community.length < 3) return null;
    const me = this.state?.players.find(p => p.id === this.myPlayerId);
    if (!me || me.is_folded) return null;
    return bestHandName([...this._myHoleCards, ...community]);
  }

  _renderMyHoleCards() {
    const el = document.getElementById(`seat-cards-${this.myPlayerId}`);
    if (!el || !this._myHoleCards) return;
    el.innerHTML = '';
    this._myHoleCards.forEach(c => el.appendChild(cardEl(c)));
  }

  renderCommunityCards() {
    const el = document.getElementById('community-cards');
    if (!el || !this.state) return;
    el.innerHTML = '';
    const cards = this.state.community_cards || [];
    for (let i = 0; i < 5; i++) {
      const slot = document.createElement('div');
      slot.className = 'card-slot';
      if (cards[i]) slot.appendChild(cardEl(cards[i]));
      el.appendChild(slot);
    }
  }

  renderPot() {
    const el = document.getElementById('pot-amount');
    if (!el || !this.state) return;
    el.textContent = `$${(this.state.pot_total || 0).toLocaleString()}`;
  }

  renderAdminPanel() {
    const panel = document.getElementById('admin-panel');
    if (!panel || !this.state) return;
    const isAdmin = this.state.admin_id === this.myPlayerId;
    panel.classList.toggle('hidden', !isAdmin);

    // Populate player dropdowns. Add Chips includes the admin themselves;
    // kick/transfer only make sense for other players.
    const others = this.state.players.filter(p => p.id !== this.myPlayerId);
    const fillSelect = (id, list) => {
      const sel = document.getElementById(id);
      if (!sel) return;
      const prev = sel.value;
      sel.innerHTML = '<option value="" disabled selected>Select Player</option>'
        + list.map(p => `<option value="${p.id}">${escapeHtml(p.display_name)}</option>`).join('');
      if (prev && list.some(p => p.id === prev)) sel.value = prev;
    };
    fillSelect('kick-target', others);
    fillSelect('transfer-target', others);
    fillSelect('chips-target', this.state.players);

    this._syncSettingsInputs();

    const startBtn = document.getElementById('start-game-btn');
    if (startBtn) {
      // Admin "Start Hand" only before the first hand; afterwards everyone uses
      // the "Deal Next Hand" button.
      const waiting = !this.state.stage || this.state.stage === 'waiting';
      startBtn.classList.toggle('hidden', !waiting || !isAdmin);
    }
  }

  // Keep the admin settings inputs showing the live values, except for
  // fields the admin is editing or has edited but not yet saved.
  _syncSettingsInputs() {
    const s = this.state?.settings || {};
    [['set-starting-chips', 'starting_chips'], ['set-small-blind', 'small_blind'], ['set-big-blind', 'big_blind']].forEach(([id, key]) => {
      const el = document.getElementById(id);
      if (!el) return;
      if (!this._settingsInputsWired) el.addEventListener('input', () => this._dirtySettingsInputs.add(id));
      if (s[key] !== undefined && document.activeElement !== el && !this._dirtySettingsInputs.has(id)) {
        el.value = s[key];
      }
    });
    this._settingsInputsWired = true;
  }

  renderStageIndicator() {
    const el = document.getElementById('stage-indicator');
    if (!el || !this.state) return;
    const labels = { waiting: 'Waiting', pre_flop: 'Pre-Flop', flop: 'Flop', turn: 'Turn', river: 'River', showdown: 'Showdown', hand_over: 'Hand Over' };
    el.textContent = labels[this.state.stage] || '';
  }

  // ---- Action panel ----

  _showActionPanel(payload) {
    const panel = document.getElementById('action-panel');
    if (!panel) return;
    panel.classList.remove('hidden');

    const foldBtn = document.getElementById('btn-fold');
    const checkBtn = document.getElementById('btn-check');
    const callBtn = document.getElementById('btn-call');
    const raiseBtn = document.getElementById('btn-raise');
    const allInBtn = document.getElementById('btn-allin');
    const raiseSection = document.getElementById('raise-section');
    const raiseSlider = document.getElementById('raise-slider');
    const raiseValue = document.getElementById('raise-value');

    const actions = payload.valid_actions || [];
    foldBtn && (foldBtn.classList.toggle('hidden', !actions.includes('fold')));
    checkBtn && (checkBtn.classList.toggle('hidden', !actions.includes('check')));
    callBtn && (callBtn.classList.toggle('hidden', !actions.includes('call')));
    raiseBtn && (raiseBtn.classList.toggle('hidden', !actions.includes('raise')));
    allInBtn && (allInBtn.classList.toggle('hidden', !actions.includes('all_in')));

    if (callBtn) callBtn.textContent = `Call $${payload.call_amount}`;

    if (raiseSlider && actions.includes('raise')) {
      raiseSection && raiseSection.classList.remove('hidden');
      const minRaise = payload.min_raise;
      const maxRaise = payload.max_raise || payload.min_raise * 10;
      raiseSlider.min = minRaise;
      raiseSlider.max = maxRaise;
      raiseSlider.value = minRaise;
      // "Bet $min" until the player picks an amount; then "Raise to $X".
      const setAmount = (v, chosen = false) => {
        raiseSlider.value = Math.max(minRaise, Math.min(maxRaise, Math.round(v)));
        if (raiseValue) raiseValue.textContent = `$${raiseSlider.value}`;
        if (raiseBtn) raiseBtn.textContent = chosen ? `Raise to $${raiseSlider.value}` : `Bet $${raiseSlider.value}`;
      };
      setAmount(minRaise);
      raiseSlider.oninput = () => setAmount(raiseSlider.value, true);

      const pot = this.state?.pot_total || 0;
      const presets = { 'preset-min': minRaise, 'preset-half': pot / 2, 'preset-pot': pot, 'preset-max': maxRaise };
      Object.entries(presets).forEach(([id, amount]) => {
        const btn = document.getElementById(id);
        if (btn) btn.onclick = () => setAmount(amount, true);
      });
    } else {
      raiseSection && raiseSection.classList.add('hidden');
    }

    this._currentActionPayload = payload;
  }

  _hideActionPanel() {
    const panel = document.getElementById('action-panel');
    panel?.classList.add('hidden');
  }

  _inPlay() {
    const s = this.state?.stage;
    return s === 'pre_flop' || s === 'flop' || s === 'turn' || s === 'river';
  }

  _remainingSeconds() {
    if (!this._turnDeadline) return 0;
    return Math.max(0, Math.ceil(this._turnDeadline - Date.now() / 1000));
  }

  // Drives both the action-panel countdown (for me) and the on-seat countdown
  // (visible to everyone) for whichever player must act before being auto-folded.
  _startTurnTimer(deadline) {
    this._stopTurnTimer();
    this._turnDeadline = deadline;
    const tick = () => {
      const remaining = this._remainingSeconds();
      const panel = document.getElementById('countdown');
      if (panel) panel.textContent = remaining;
      const seat = document.getElementById('seat-timer');
      if (seat) {
        seat.textContent = `${remaining}s`;
        seat.classList.toggle('seat-timer-urgent', remaining <= 5);
      }
      if (remaining <= 0) clearInterval(this.turnTimerInterval);
    };
    tick();
    this.turnTimerInterval = setInterval(tick, 250);
  }

  _stopTurnTimer() {
    clearInterval(this.turnTimerInterval);
    this._turnDeadline = null;
    const panel = document.getElementById('countdown');
    if (panel) panel.textContent = '';
  }

  _log(text) {
    const ts = new Date().toISOString();
    this._chat?.addSystemMessage(text, ts);
  }
}

function cardEl(card) {
  const el = document.createElement('div');
  el.className = 'card';
  const isRed = card.suit === 'hearts' || card.suit === 'diamonds';
  el.classList.add(isRed ? 'card-red' : 'card-black');
  const suit = SUIT_SYMBOL[card.suit] || card.suit;
  el.innerHTML = `<span class="card-idx"><span class="card-rank">${card.rank}</span><span class="card-suit">${suit}</span></span><span class="card-pip">${suit}</span>`;
  return el;
}

function escapeHtml(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function showToast(message, type = 'info') {
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.textContent = message;
  document.body.appendChild(toast);
  setTimeout(() => toast.classList.add('toast-show'), 50);
  setTimeout(() => { toast.classList.remove('toast-show'); setTimeout(() => toast.remove(), 300); }, 3500);
}

window.GameState = GameState;
window.cardEl = cardEl;
window.escapeHtml = escapeHtml;
window.showToast = showToast;
