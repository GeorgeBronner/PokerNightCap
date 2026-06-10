class ChatBox {
  constructor(containerEl) {
    this._container = containerEl;
    this._chatList = containerEl.querySelector('#chat-messages');
    this._logList = containerEl.querySelector('#log-messages');
    this._input = containerEl.querySelector('#chat-input');
    this._sendBtn = containerEl.querySelector('#chat-send');
    this._chatTab = containerEl.querySelector('#tab-chat');
    this._logTab = containerEl.querySelector('#tab-log');
    this._chatBadge = containerEl.querySelector('#chat-badge');
    this._logBadge = containerEl.querySelector('#log-badge');
    this._activeTab = 'log';
    this._unreadChat = 0;
    this._unreadLog = 0;
    this._onSend = null;

    this._chatTab.addEventListener('click', () => this._switchTab('chat'));
    this._logTab.addEventListener('click', () => this._switchTab('log'));
    this._sendBtn.addEventListener('click', () => this._sendMessage());
    this._input.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); this._sendMessage(); } });

    this._switchTab('log');
  }

  onSend(fn) { this._onSend = fn; }

  addSystemMessage(text, timestamp) {
    const el = this._makeEntry('System', text, timestamp, true);
    this._logList.appendChild(el);
    if (this._activeTab !== 'log') {
      this._unreadLog++;
      this._logBadge.textContent = this._unreadLog;
      this._logBadge.classList.remove('hidden');
    } else {
      this._scrollBottom(this._logList);
    }
  }

  addChatMessage(senderName, text, timestamp) {
    const el = this._makeEntry(senderName, text, timestamp, false);
    this._chatList.appendChild(el);
    if (this._activeTab !== 'chat') {
      this._unreadChat++;
      this._chatBadge.textContent = this._unreadChat;
      this._chatBadge.classList.remove('hidden');
    } else {
      this._scrollBottom(this._chatList);
    }
  }

  _makeEntry(sender, text, timestamp, isSystem) {
    const el = document.createElement('div');
    el.className = `chat-entry${isSystem ? ' chat-system' : ''}`;
    const time = timestamp ? new Date(timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '';
    el.innerHTML = `<span class="chat-sender">${isSystem ? '' : sender + ': '}</span><span class="chat-text">${this._escapeHtml(text)}</span><span class="chat-time">${time}</span>`;
    return el;
  }

  _escapeHtml(s) {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  _switchTab(tab) {
    this._activeTab = tab;
    if (tab === 'chat') {
      this._chatList.classList.remove('hidden');
      this._logList.classList.add('hidden');
      this._chatTab.classList.add('tab-active');
      this._logTab.classList.remove('tab-active');
      this._unreadChat = 0;
      this._chatBadge.classList.add('hidden');
      this._scrollBottom(this._chatList);
    } else {
      this._logList.classList.remove('hidden');
      this._chatList.classList.add('hidden');
      this._logTab.classList.add('tab-active');
      this._chatTab.classList.remove('tab-active');
      this._unreadLog = 0;
      this._logBadge.classList.add('hidden');
      this._scrollBottom(this._logList);
    }
  }

  _scrollBottom(el) {
    el.scrollTop = el.scrollHeight;
  }

  _sendMessage() {
    const text = this._input.value.trim();
    if (!text || !this._onSend) return;
    this._onSend(text);
    this._input.value = '';
  }
}

window.ChatBox = ChatBox;
