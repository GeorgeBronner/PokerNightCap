class PokerSocket {
  constructor() {
    this._ws = null;
    this._handlers = {};
    this._reconnectAttempts = 0;
    this._maxAttempts = 5;
    this._pingInterval = null;
    this._pongTimeout = null;
    this._intentionalClose = false;
    this._pendingFirstMsg = null;
  }

  connect(roomCode, firstMessage) {
    this._pendingFirstMsg = firstMessage;
    this._roomCode = roomCode;
    this._intentionalClose = false;
    this._open();
  }

  _open() {
    const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
    const url = `${protocol}://${location.host}/ws/${this._roomCode}`;
    this._ws = new WebSocket(url);

    this._ws.onopen = () => {
      if (this._pendingFirstMsg) {
        this._ws.send(JSON.stringify(this._pendingFirstMsg));
        this._pendingFirstMsg = null;
      }
      this._startPing();
      this._emit('_connected', {});
    };

    this._ws.onmessage = (event) => {
      let data;
      try { data = JSON.parse(event.data); } catch { return; }
      if (data.type === 'pong') {
        clearTimeout(this._pongTimeout);
        return;
      }
      // Only a confirmed join resets the retry budget — the socket itself
      // always opens even when the server is about to reject the join, so
      // resetting in onopen would retry a doomed join forever.
      if (data.type === 'room_joined') {
        this._reconnectAttempts = 0;
      }
      // The room no longer exists (e.g. server restarted): retrying is futile.
      if (data.type === 'error' && data.payload && data.payload.code === 'room_not_found') {
        this._intentionalClose = true;
      }
      this._emit(data.type, data.payload || {});
    };

    this._ws.onclose = () => {
      this._stopPing();
      if (!this._intentionalClose) {
        this._scheduleReconnect();
      }
      this._emit('_disconnected', {});
    };

    this._ws.onerror = () => {
      this._ws.close();
    };
  }

  _scheduleReconnect() {
    if (this._reconnectAttempts >= this._maxAttempts) {
      this._emit('_reconnect_failed', {});
      return;
    }
    const delay = Math.min(1000 * Math.pow(2, this._reconnectAttempts), 30000);
    this._reconnectAttempts++;
    setTimeout(() => {
      const token = sessionStorage.getItem('reconnect_token');
      const roomCode = sessionStorage.getItem('room_code');
      const displayName = sessionStorage.getItem('display_name');
      if (token && roomCode) {
        this._pendingFirstMsg = { type: 'join_room', room_code: roomCode, display_name: displayName || '', reconnect_token: token };
        this._roomCode = roomCode;
        this._open();
      }
    }, delay);
  }

  _startPing() {
    this._stopPing();
    this._pingInterval = setInterval(() => {
      if (this._ws && this._ws.readyState === WebSocket.OPEN) {
        this._ws.send(JSON.stringify({ type: 'ping' }));
        this._pongTimeout = setTimeout(() => {
          this._ws.close();
        }, 5000);
      }
    }, 20000);
  }

  _stopPing() {
    clearInterval(this._pingInterval);
    clearTimeout(this._pongTimeout);
  }

  send(data) {
    if (this._ws && this._ws.readyState === WebSocket.OPEN) {
      this._ws.send(JSON.stringify(data));
    }
  }

  on(type, handler) {
    if (!this._handlers[type]) this._handlers[type] = [];
    this._handlers[type].push(handler);
    return this;
  }

  off(type, handler) {
    if (this._handlers[type]) {
      this._handlers[type] = this._handlers[type].filter(h => h !== handler);
    }
  }

  _emit(type, payload) {
    (this._handlers[type] || []).forEach(h => h(payload));
  }

  close() {
    this._intentionalClose = true;
    this._stopPing();
    if (this._ws) this._ws.close();
  }
}

window.PokerSocket = PokerSocket;
