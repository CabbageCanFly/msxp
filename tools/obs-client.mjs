// Minimal OBS WebSocket v5 client for this local acquisition experiment.
// Passwords are used only for the local challenge and never stored or uploaded.
export async function authentication(password, salt, challenge) {
  const hash = async text => {
    const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
    return btoa(String.fromCharCode(...new Uint8Array(bytes)));
  };
  return hash((await hash(password + salt)) + challenge);
}

export function cropBox(roi, width, height) {
  if (roi.length !== 4 || !roi.every(Number.isFinite) ||
      !(0 <= roi[0] && roi[0] < roi[2] && roi[2] <= 1 &&
        0 <= roi[1] && roi[1] < roi[3] && roi[3] <= 1)) {
    throw new Error("Crop must be x0,y0,x1,y1 fractions between 0 and 1");
  }
  const x = Math.floor(roi[0] * width), y = Math.floor(roi[1] * height);
  return [x, y, Math.ceil(roi[2] * width) - x, Math.ceil(roi[3] * height) - y];
}

export class OBSClient {
  constructor(port = 4455) {
    if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error("Invalid local port");
    this.port = port;
    this.pending = new Map();
    this.ready = false;
    this.sequence = 0;
  }

  connect(password) {
    return new Promise((resolve, reject) => {
      const socket = this.socket = new WebSocket(`ws://127.0.0.1:${this.port}`);
      const timer = setTimeout(() => { reject(new Error("OBS handshake timed out")); this.close(); }, 10000);
      const fail = error => { clearTimeout(timer); reject(error); this.close(); };
      socket.onmessage = async event => {
        try {
          const message = JSON.parse(event.data);
          if (message.op === 0) {
            if (!message.d.authentication) throw new Error("Enable OBS WebSocket password authentication first");
            const {salt, challenge} = message.d.authentication;
            const auth = await authentication(password, salt, challenge);
            password = "";
            socket.send(JSON.stringify({op: 1, d: {rpcVersion: 1, eventSubscriptions: 0, authentication: auth}}));
          } else if (message.op === 2) {
            clearTimeout(timer);
            this.ready = true;
            resolve();
          } else if (message.op === 7) {
            const pending = this.pending.get(message.d.requestId);
            if (!pending) return;
            clearTimeout(pending.timer);
            this.pending.delete(message.d.requestId);
            if (message.d.requestStatus.result) pending.resolve(message.d.responseData);
            else pending.reject(new Error(`OBS request failed: ${message.d.requestStatus.code}`));
          }
        } catch (error) { fail(error); }
      };
      socket.onerror = () => fail(new Error("Cannot connect to local OBS; check OBS settings and browser restrictions"));
      socket.onclose = event => {
        clearTimeout(timer);
        this.ready = false;
        const error = new Error(`OBS disconnected (${event.code}); check authentication if code 4009`);
        reject(error);
        for (const pending of this.pending.values()) { clearTimeout(pending.timer); pending.reject(error); }
        this.pending.clear();
      };
    });
  }

  request(requestType, requestData = {}) {
    if (!this.ready) return Promise.reject(new Error("Connect to OBS first"));
    const requestId = String(++this.sequence);
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(requestId);
        reject(new Error("OBS request timed out"));
      }, 10000);
      this.pending.set(requestId, {resolve, reject, timer});
      this.socket.send(JSON.stringify({op: 6, d: {requestType, requestId, requestData}}));
    });
  }

  close() { this.ready = false; this.socket?.close(); }
}
