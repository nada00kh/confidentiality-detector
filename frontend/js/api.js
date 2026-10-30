// The only place the pages talk to the backend.
// Every page calls WashqAPI.<function>(). In demo mode these come from js/mock.js;
// otherwise they call the FastAPI endpoints described in API_CONTRACT.md.
(function () {
  const cfg = window.WASHQ_CONFIG;
  const CHECK_TIMEOUT_MS = cfg.CHECK_TIMEOUT_MS > 0 ? cfg.CHECK_TIMEOUT_MS : 60000;

  async function request(method, path, body, signal) {
    let res;
    try {
      res = await fetch(cfg.API_BASE + path, {
        method,
        headers: body ? { "Content-Type": "application/json" } : undefined,
        body: body ? JSON.stringify(body) : undefined,
        signal
      });
    } catch (e) {
      throw new Error(`Couldn’t reach the WASHQ server at ${cfg.API_BASE}.`);
    }
    if (!res.ok) {
      let message = `The server answered ${res.status}.`;
      try {
        const data = await res.json();
        if (typeof data.detail === "string") message = data.detail;
      } catch (e) { /* keep the default message */ }
      throw new Error(message);
    }
    return res.json();
  }

  function query(params) {
    const p = new URLSearchParams();
    Object.entries(params || {}).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== "") p.set(k, v);
    });
    const s = p.toString();
    return s ? `?${s}` : "";
  }

  // Fails with a clear error after `ms`. The request is cancelled, and the race is settled by then,
  // so an answer that arrives later can never become a result.
  function withTimeout(run, ms) {
    const controller = new AbortController();
    let timer;
    const timeout = new Promise((_, reject) => {
      timer = setTimeout(() => {
        controller.abort();
        reject(new Error(`No answer within ${Math.round(ms / 1000)} seconds, so the scan was stopped. Please try again.`));
      }, ms);
    });
    return Promise.race([run(controller.signal), timeout]).finally(() => clearTimeout(timer));
  }

  const live = {
    check: (text) => withTimeout((signal) => request("POST", "/api/check", { text }, signal), CHECK_TIMEOUT_MS),
    stats: (days) => request("GET", "/api/stats" + query({ days })),
    logs: (params) => request("GET", "/api/logs" + query(params))
  };

  window.WashqAPI = Object.assign({}, cfg.USE_MOCK ? window.WashqMock : live, { isMock: !!cfg.USE_MOCK });
})();
