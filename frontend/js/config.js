// WASHQ frontend settings.
// While the backend isn't ready, the pages run on demo data from js/mock.js.
// When the FastAPI server is running, set USE_MOCK to false. Nothing else in the pages needs to change.
window.WASHQ_CONFIG = {
  USE_MOCK: false,
  API_BASE: "http://localhost:8000",
  MOCK_DELAY_MS: 900
};
