// The only place the pages talk to the backend.
// Every page calls WashqAPI.<function>(). In demo mode these come from js/mock.js;
// otherwise they call the FastAPI endpoints described in API_CONTRACT.md.
(function () {
  const cfg = window.WASHQ_CONFIG;

  async function request(method, path, body) {
    let res;
    try {
      res = await fetch(cfg.API_BASE + path, {
        method,
        headers: body ? { "Content-Type": "application/json" } : undefined,
        body: body ? JSON.stringify(body) : undefined
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

  const live = {
    check: (text) => request("POST", "/api/check", { text }),
    stats: (days) => request("GET", "/api/stats" + query({ days })),
    logs: (params) => request("GET", "/api/logs" + query(params))
  };

  window.WashqAPI = Object.assign({}, cfg.USE_MOCK ? window.WashqMock : live, { isMock: !!cfg.USE_MOCK });
})();
