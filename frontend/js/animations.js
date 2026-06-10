const Animations = (() => {
  const DECK_POS = { x: '50%', y: '50%' };

  function _getCardEl(rank, suit) {
    const el = document.createElement('div');
    el.className = 'card card-anim';
    const isRed = suit === 'hearts' || suit === 'diamonds';
    el.classList.add(isRed ? 'card-red' : 'card-black');
    const symbols = { clubs: '♣', diamonds: '♦', hearts: '♥', spades: '♠' };
    const sym = symbols[suit] || suit;
    el.innerHTML = `<span class="card-idx"><span class="card-rank">${rank}</span><span class="card-suit">${sym}</span></span><span class="card-pip">${sym}</span>`;
    return el;
  }

  function dealCard(targetEl, card, delay = 0) {
    return new Promise(resolve => {
      const el = _getCardEl(card.rank, card.suit);
      el.style.cssText = 'position:fixed;left:50%;top:50%;transform:translate(-50%,-50%) scale(0.3);opacity:0;transition:none;z-index:100;';
      document.body.appendChild(el);

      const rect = targetEl.getBoundingClientRect();
      const destX = rect.left + rect.width / 2;
      const destY = rect.top + rect.height / 2;

      setTimeout(() => {
        el.style.transition = 'all 0.35s cubic-bezier(.4,0,.2,1)';
        el.style.left = destX + 'px';
        el.style.top = destY + 'px';
        el.style.transform = 'translate(-50%,-50%) scale(1)';
        el.style.opacity = '1';

        setTimeout(() => {
          el.remove();
          resolve();
        }, 380);
      }, delay);
    });
  }

  async function dealHoleCards(seatEls) {
    for (let round = 0; round < 2; round++) {
      for (let i = 0; i < seatEls.length; i++) {
        const el = seatEls[i];
        if (el) {
          const placeholder = document.createElement('div');
          placeholder.className = 'card card-back';
          el.querySelector('.seat-cards')?.appendChild(placeholder);
        }
        await new Promise(r => setTimeout(r, 80));
      }
    }
  }

  async function dealCommunityCards(containerEl, cards) {
    for (let i = 0; i < cards.length; i++) {
      const card = cards[i];
      const slot = containerEl.children[i];
      if (slot) {
        await dealCard(slot, card, i * 100);
      }
    }
  }

  function chipsToPot(fromEl, potEl) {
    return new Promise(resolve => {
      const chip = document.createElement('div');
      chip.className = 'chip-anim';
      chip.textContent = '●';
      const from = fromEl.getBoundingClientRect();
      const to = potEl.getBoundingClientRect();
      chip.style.cssText = `position:fixed;left:${from.left + from.width / 2}px;top:${from.top + from.height / 2}px;font-size:20px;color:#f59e0b;z-index:200;transition:all 0.4s ease;pointer-events:none;`;
      document.body.appendChild(chip);
      requestAnimationFrame(() => {
        chip.style.left = (to.left + to.width / 2) + 'px';
        chip.style.top = (to.top + to.height / 2) + 'px';
        chip.style.opacity = '0';
      });
      setTimeout(() => { chip.remove(); resolve(); }, 450);
    });
  }

  return { dealCard, dealHoleCards, dealCommunityCards, chipsToPot };
})();

window.Animations = Animations;
