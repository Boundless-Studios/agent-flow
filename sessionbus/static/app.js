(function () {
  const REFRESH_INTERVAL_MS = 10000;

  async function refreshSections() {
    const sections = document.querySelectorAll("[data-refresh-url]");
    if (!sections.length) {
      return;
    }

    await Promise.all(
      Array.from(sections).map(async (section) => {
        const refreshUrl = section.getAttribute("data-refresh-url");
        if (!refreshUrl) {
          return;
        }

        try {
          const response = await fetch(refreshUrl, { cache: "no-store" });
          if (!response.ok) {
            return;
          }
          section.innerHTML = await response.text();
        } catch (_err) {
          // Ignore transient refresh errors; next event/poll will retry.
        }
      })
    );
  }

  function attachEventStream() {
    if (typeof window.EventSource === "undefined") {
      return false;
    }

    const eventSource = new EventSource("/api/events");
    eventSource.onmessage = function () {
      void refreshSections();
    };
    eventSource.onerror = function () {
      // Keep stream open; browser will reconnect automatically.
    };
    return true;
  }

  document.addEventListener("DOMContentLoaded", function () {
    const sseAttached = attachEventStream();
    if (!sseAttached) {
      setInterval(function () {
        void refreshSections();
      }, REFRESH_INTERVAL_MS);
    }
  });
})();
