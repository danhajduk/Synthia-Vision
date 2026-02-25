(function () {
  function initEmbeddedMode() {
    try {
      var params = new URLSearchParams(window.location.search);
      var embeddedFlag = params.has('embed') || params.has('embedded') || params.get('ha_embed') === '1';
      var inFrame = window.self !== window.top;
      var haReferrer = /homeassistant|hassio|lovelace/i.test(document.referrer || '');
      if (embeddedFlag || inFrame || haReferrer) {
        document.body.classList.add('is-embedded');
      }
    } catch (err) {
      document.body.classList.add('is-embedded');
    }
  }

  function nowTs() {
    return Date.now();
  }

  function pad2(value) {
    return String(value).padStart(2, '0');
  }

  function formatLocalTimestamp(raw) {
    const value = String(raw || '').trim();
    if (!value) {
      return '—';
    }
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) {
      return '—';
    }
    const now = new Date();
    const isToday =
      parsed.getFullYear() === now.getFullYear() &&
      parsed.getMonth() === now.getMonth() &&
      parsed.getDate() === now.getDate();
    if (isToday) {
      return pad2(parsed.getHours()) + ':' + pad2(parsed.getMinutes());
    }
    return (
      parsed.getFullYear() +
      '-' + pad2(parsed.getMonth() + 1) +
      '-' + pad2(parsed.getDate()) +
      ' ' + pad2(parsed.getHours()) +
      ':' + pad2(parsed.getMinutes())
    );
  }

  function formatLocalDateTime(raw) {
    const value = String(raw || '').trim();
    if (!value) {
      return '—';
    }
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) {
      return '—';
    }
    return (
      pad2(parsed.getMonth() + 1) +
      '/' + pad2(parsed.getDate()) +
      '/' + parsed.getFullYear() +
      ' ' + pad2(parsed.getHours()) +
      ':' + pad2(parsed.getMinutes()) +
      ':' + pad2(parsed.getSeconds())
    );
  }

  function scheduleWithJitter(baseMs) {
    const jitter = Math.floor((Math.random() * 600) - 300);
    return Math.max(500, baseMs + jitter);
  }

  function initGuestPreview() {
    const cfgRaw = window.SYNTHIA_PREVIEW_CONFIG || {};
    const cfg = {
      enabled: Boolean(cfgRaw.enabled),
      enabledIntervalS: Number(cfgRaw.enabledIntervalS) || 2,
      disabledIntervalS: Number(cfgRaw.disabledIntervalS) || 60,
      maxActive: Number(cfgRaw.maxActive) || 1,
    };
    const cards = Array.from(document.querySelectorAll('[data-camera-card]'));
    if (!cards.length) {
      return;
    }

    const state = new Map();
    cards.forEach((card) => {
      state.set(card, {
        visible: false,
        timer: null,
      });
    });

    function activeVisibleCards() {
      return cards.filter((card) => {
        const s = state.get(card);
        if (!s || !s.visible) {
          return false;
        }
        return true;
      });
    }

    async function refreshCardData(card) {
      const cameraKey = card.getAttribute('data-camera-key');
      if (!cameraKey) {
        return;
      }
      try {
        const resp = await fetch('/api/cameras/' + encodeURIComponent(cameraKey) + '/card', {
          credentials: 'same-origin',
        });
        if (!resp.ok) {
          return;
        }
        const data = await resp.json();
        const enabled = Boolean(data.enabled);
        card.classList.toggle('is-disabled', !enabled);
        card.setAttribute('data-camera-enabled', enabled ? '1' : '0');

        const enabledValueEl = card.querySelector('[data-enabled-value]');
        if (enabledValueEl) {
          enabledValueEl.textContent = enabled ? 'Yes' : 'No';
        }

        const lastSeenEl = card.querySelector('[data-last-seen]');
        if (lastSeenEl) {
          const raw = String(data.last_seen_ts || '');
          lastSeenEl.setAttribute('data-last-seen', raw);
          lastSeenEl.textContent = formatLocalTimestamp(raw);
        }

        const lastActionEl = card.querySelector('[data-last-action]');
        if (lastActionEl) {
          lastActionEl.textContent = data.last_action_confidence || '—';
        }
        const mtdCostEl = card.querySelector('[data-mtd-cost]');
        if (mtdCostEl) {
          mtdCostEl.textContent = data.mtd_cost || '—';
        }

        const statusTextEl = card.querySelector('[data-status-text]');
        const statusDotEl = card.querySelector('[data-status-pill] .dot');
        const status = String(data.status || 'disabled');
        if (statusTextEl) {
          statusTextEl.textContent = status === 'ok' ? 'OK' : (status === 'degraded' ? 'Degraded' : 'Disabled');
        }
        if (statusDotEl) {
          statusDotEl.classList.remove('warn', 'bad');
          if (status === 'degraded') {
            statusDotEl.classList.add('warn');
          } else if (status === 'disabled') {
            statusDotEl.classList.add('bad');
          }
        }
      } catch (err) {
        // Keep existing card values on transient fetch failures.
      }
    }

    function refreshCard(card) {
      const img = card.querySelector('[data-preview-img]');
      refreshCardData(card);
      if (!img || !cfg.enabled || card.getAttribute('data-preview-enabled') !== '1') {
        return;
      }
      const cameraKey = card.getAttribute('data-camera-key');
      img.style.opacity = '0.9';
      img.addEventListener('load', function onLoad() {
        img.style.opacity = '1';
        img.removeEventListener('load', onLoad);
      });
      img.src = '/api/cameras/' + encodeURIComponent(cameraKey) + '/preview.jpg?ts=' + String(nowTs());
    }

    function clearTimer(card) {
      const s = state.get(card);
      if (!s || !s.timer) {
        return;
      }
      clearTimeout(s.timer);
      s.timer = null;
    }

    function armTimer(card) {
      clearTimer(card);
      const isEnabled = card.getAttribute('data-camera-enabled') === '1';
      const baseMs = (isEnabled ? cfg.enabledIntervalS : cfg.disabledIntervalS) * 1000;
      const s = state.get(card);
      if (!s) {
        return;
      }
      s.timer = setTimeout(function loop() {
        refreshCard(card);
        armTimer(card);
      }, scheduleWithJitter(baseMs));
    }

    function rebalance() {
      const visible = activeVisibleCards();
      const allowed = visible.slice(0, Math.max(1, Number(cfg.maxActive) || 1));
      cards.forEach((card) => {
        const shouldRun = allowed.indexOf(card) >= 0;
        if (shouldRun) {
          if (!state.get(card).timer) {
            refreshCard(card);
            armTimer(card);
          }
        } else {
          clearTimer(card);
        }
      });
    }

    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        const card = entry.target;
        const s = state.get(card);
        if (!s) {
          return;
        }
        s.visible = entry.isIntersecting;
        if (!entry.isIntersecting) {
          clearTimer(card);
        }
      });
      rebalance();
    }, { threshold: 0.2 });

    cards.forEach((card) => observer.observe(card));
    window.addEventListener('beforeunload', function () {
      cards.forEach(clearTimer);
      observer.disconnect();
    });
  }

  function initGuestTimestamps() {
    const nodes = Array.from(document.querySelectorAll('[data-last-seen]'));
    if (!nodes.length) {
      return;
    }

    nodes.forEach((node) => {
      node.textContent = formatLocalTimestamp(node.getAttribute('data-last-seen'));
    });
  }

  function initGuestKpiRefresh() {
    const healthLabelEl = document.querySelector('[data-kpi-health-label]');
    if (!healthLabelEl) {
      return;
    }

    const healthBadgeTextEl = document.querySelector('[data-kpi-health-badge-text]');
    const healthDotEl = document.querySelector('[data-kpi-health-dot]');
    const heartbeatEl = document.querySelector('[data-kpi-heartbeat]');
    const queueRatioEl = document.querySelector('[data-kpi-queue-ratio]');
    const queueDepthEl = document.querySelector('[data-kpi-queue-depth]');
    const dropsEl = document.querySelector('[data-kpi-drops]');
    const costTodayEl = document.querySelector('[data-kpi-cost-today]');
    const costMtdEl = document.querySelector('[data-kpi-cost-mtd]');
    const costAvgEventEl = document.querySelector('[data-kpi-cost-avg-event]');
    const aiCallsEl = document.querySelector('[data-kpi-ai-calls]');
    const tokensTodayEl = document.querySelector('[data-kpi-tokens-today]');
    const avgTokensEventEl = document.querySelector('[data-kpi-avg-tokens-event]');

    const queueMax = 50;
    let inFlight = false;

    function asInt(value, fallback) {
      const parsed = Number.parseInt(String(value), 10);
      return Number.isFinite(parsed) ? parsed : fallback;
    }

    function asFloat(value, fallback) {
      const parsed = Number.parseFloat(String(value));
      return Number.isFinite(parsed) ? parsed : fallback;
    }

    function money(value) {
      return '$' + asFloat(value, 0).toFixed(4);
    }

    function healthInfo(statusRaw) {
      const status = String(statusRaw || 'unknown').toLowerCase();
      if (status === 'enabled') {
        return { label: 'Healthy', badge: 'Enabled', dot: '' };
      }
      if (status === 'degraded') {
        return { label: 'Degraded', badge: 'Degraded', dot: 'warn' };
      }
      if (status === 'disabled') {
        return { label: 'Disabled', badge: 'Disabled', dot: 'bad' };
      }
      if (status === 'budget_blocked') {
        return { label: 'Budget Blocked', badge: 'Budget Blocked', dot: 'bad' };
      }
      return { label: 'Unknown', badge: 'Unknown', dot: '' };
    }

    async function refreshOnce() {
      if (inFlight) {
        return;
      }
      inFlight = true;
      try {
        const [statusResp, metricsResp] = await Promise.all([
          fetch('/api/status', { credentials: 'same-origin' }),
          fetch('/api/metrics/summary', { credentials: 'same-origin' }),
        ]);
        if (!statusResp.ok || !metricsResp.ok) {
          return;
        }
        const statusPayload = await statusResp.json();
        const metricsPayload = await metricsResp.json();
        const metrics = metricsPayload && metricsPayload.metrics ? metricsPayload.metrics : {};

        const health = healthInfo(statusPayload.service_status);
        healthLabelEl.textContent = health.label;
        if (healthBadgeTextEl) {
          healthBadgeTextEl.textContent = health.badge;
        }
        if (healthDotEl) {
          healthDotEl.classList.remove('warn', 'bad');
          if (health.dot) {
            healthDotEl.classList.add(health.dot);
          }
        }
        if (heartbeatEl) {
          heartbeatEl.textContent = formatLocalDateTime(
            statusPayload.heartbeat_ts || statusPayload.timestamp || ''
          );
        }

        const queueDepth = asInt(metrics.queue_depth, 0);
        if (queueDepthEl) {
          queueDepthEl.textContent = String(queueDepth);
        }
        if (queueRatioEl) {
          queueRatioEl.textContent = String(queueDepth) + ' / ' + String(queueMax);
        }
        if (dropsEl) {
          dropsEl.textContent = String(asInt(metrics.dropped_events_total, 0));
        }

        if (costTodayEl) {
          costTodayEl.textContent = money(metrics.cost_daily_total);
        }
        if (costMtdEl) {
          costMtdEl.textContent = money(metrics.cost_month2day_total);
        }
        if (costAvgEventEl) {
          costAvgEventEl.textContent = money(metrics.cost_avg_per_event);
        }
        if (aiCallsEl) {
          aiCallsEl.textContent = String(asInt(metrics.count_today, 0));
        }
        if (tokensTodayEl) {
          tokensTodayEl.textContent = String(asInt(metrics.tokens_today_total, 0));
        }
        if (avgTokensEventEl) {
          avgTokensEventEl.textContent = String(Math.round(asFloat(metrics.avg_tokens_per_event, 0)));
        }
      } catch (err) {
        // Keep current values when polling temporarily fails.
      } finally {
        inFlight = false;
      }
    }

    refreshOnce();
    window.setInterval(refreshOnce, 2000);
  }

  async function guardAdminUiRoute() {
    const page = document.body.getAttribute('data-ui-page') || '';
    if (['admin', 'setup', 'events', 'errors'].indexOf(page) < 0) {
      return true;
    }
    try {
      const resp = await fetch('/api/auth/me', { credentials: 'same-origin' });
      if (resp.status === 401 || resp.status === 403) {
        window.location.href = '/ui/login';
        return false;
      }
      return resp.ok;
    } catch (err) {
      return false;
    }
  }

  function initAdminPage() {
    const logoutBtn = document.getElementById('admin-logout');
    if (!logoutBtn) {
      return;
    }
    const statusEl = document.getElementById('admin-summary-status');
    const fields = {
      health_label: document.getElementById('admin-kpi-health-label'),
      health_badge_text: document.getElementById('admin-kpi-health-badge-text'),
      health_dot: (function () {
        const pill = document.getElementById('admin-kpi-health-badge');
        return pill ? pill.querySelector('.dot') : null;
      })(),
      heartbeat: document.getElementById('admin-kpi-heartbeat'),
      queue_depth: document.getElementById('admin-kpi-queue-depth'),
      queue_ratio: document.getElementById('admin-kpi-queue-ratio'),
      last_event_ts: document.getElementById('admin-last-event-ts'),
      events_total: document.getElementById('admin-events-total'),
      errors_total: document.getElementById('admin-errors-total'),
    };
    const queueMax = 50;

    function healthInfo(statusRaw) {
      const status = String(statusRaw || 'unknown').toLowerCase();
      if (status === 'enabled') {
        return { label: 'Healthy', badge: 'Enabled', dot: '' };
      }
      if (status === 'degraded') {
        return { label: 'Degraded', badge: 'Degraded', dot: 'warn' };
      }
      if (status === 'disabled') {
        return { label: 'Disabled', badge: 'Disabled', dot: 'bad' };
      }
      if (status === 'budget_blocked') {
        return { label: 'Budget Blocked', badge: 'Budget Blocked', dot: 'bad' };
      }
      return { label: 'Unknown', badge: 'Unknown', dot: '' };
    }

    async function loadSummary() {
      try {
        const resp = await fetch('/api/admin/summary', { credentials: 'same-origin' });
        if (!resp.ok) {
          if (statusEl) {
            statusEl.textContent = 'Failed to load summary.';
          }
          return;
        }
        const data = await resp.json();
        const health = healthInfo(data.service_status);
        if (fields.health_label) {
          fields.health_label.textContent = health.label;
        }
        if (fields.health_badge_text) {
          fields.health_badge_text.textContent = health.badge;
        }
        if (fields.health_dot) {
          fields.health_dot.classList.remove('warn', 'bad');
          if (health.dot) {
            fields.health_dot.classList.add(health.dot);
          }
        }
        if (fields.heartbeat) {
          fields.heartbeat.textContent = formatLocalDateTime(data.heartbeat_ts);
        }
        if (fields.queue_depth) {
          fields.queue_depth.textContent = String(data.queue_depth ?? '—');
        }
        if (fields.queue_ratio) {
          fields.queue_ratio.textContent = String(data.queue_depth ?? 0) + ' / ' + String(queueMax);
        }
        if (fields.last_event_ts) {
          fields.last_event_ts.textContent = formatLocalDateTime(data.last_event_ts);
        }
        if (fields.events_total) {
          fields.events_total.textContent = String(data.events_total ?? '0');
        }
        if (fields.errors_total) {
          fields.errors_total.textContent = String(data.errors_total ?? '0');
        }
        if (statusEl) {
          statusEl.textContent = 'Updated ' + formatLocalDateTime(new Date().toISOString());
        }
      } catch (err) {
        if (statusEl) {
          statusEl.textContent = 'Failed to load summary.';
        }
      }
    }

    logoutBtn.addEventListener('click', async function () {
      try {
        await fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' });
      } finally {
        window.location.href = '/ui/login';
      }
    });
    loadSummary();
    window.setInterval(loadSummary, 5000);
  }

  function initEventsPage() {
    const tableBody = document.getElementById('events-table-body');
    if (!tableBody) {
      return;
    }
    const statusEl = document.getElementById('events-status');
    const pageLabelEl = document.getElementById('events-page-label');
    const prevBtn = document.getElementById('events-prev');
    const nextBtn = document.getElementById('events-next');
    const refreshBtn = document.getElementById('events-refresh');
    const detailOverlay = document.getElementById('events-detail-overlay');
    const detailClose = document.getElementById('events-detail-close');
    const detailJson = document.getElementById('events-detail-json');
    const detailReason = document.getElementById('events-detail-reason');
    const detailSnapshot = document.getElementById('events-detail-snapshot');
    const state = { limit: 50, offset: 0, total: 0, items: [] };

    function queryFilters() {
      const params = new URLSearchParams(window.location.search);
      const filter = {
        camera: String(params.get('camera') || '').trim(),
        status: String(params.get('status') || '').trim().toLowerCase(),
        since: String(params.get('since') || '').trim(),
      };
      return filter;
    }

    function renderRows(items) {
      tableBody.innerHTML = '';
      if (!items.length) {
        tableBody.innerHTML = '<tr><td colspan="4">No events yet.</td></tr>';
        return;
      }
      items.forEach(function (item) {
        const tr = document.createElement('tr');
        tr.setAttribute('data-event-row', '1');
        tr.setAttribute('data-event-id', item.event_id || '');
        tr.innerHTML =
          '<td>' + formatLocalDateTime(item.ts) + '</td>' +
          '<td>' + (item.camera || '—') + '</td>' +
          '<td>' + (item.result_status || '—') + '</td>' +
          '<td><a href="#" data-event-link>' + (item.event_id || '—') + '</a></td>';
        tableBody.appendChild(tr);
      });
    }

    async function openDetail(eventId) {
      try {
        const resp = await fetch('/api/events/' + encodeURIComponent(eventId), { credentials: 'same-origin' });
        if (!resp.ok) {
          return;
        }
        const data = await resp.json();
        detailJson.textContent = JSON.stringify(data, null, 2);
        detailReason.textContent = 'Status reason: ' + String(data.reject_reason || data.result_status || '—');
        detailSnapshot.textContent = 'Snapshot URL: /api/events/' + eventId + '/snapshot.jpg';
        detailOverlay.hidden = false;
      } catch (err) {
        // ignore
      }
    }

    async function loadPage() {
      const filters = queryFilters();
      const params = new URLSearchParams({
        limit: String(state.limit),
        offset: String(state.offset),
      });
      if (filters.camera) {
        params.set('camera', filters.camera);
      }
      if (filters.status === 'accepted' || filters.status === 'ok' || filters.status === 'approved') {
        params.set('accepted', 'true');
      } else if (filters.status === 'rejected' || filters.status === 'denied') {
        params.set('accepted', 'false');
      }
      const resp = await fetch('/api/events?' + params.toString(), { credentials: 'same-origin' });
      if (!resp.ok) {
        statusEl.textContent = 'Failed loading events.';
        return;
      }
      const payload = await resp.json();
      let items = Array.isArray(payload.items) ? payload.items : [];
      if (filters.since) {
        const sinceTime = new Date(filters.since).getTime();
        if (!Number.isNaN(sinceTime)) {
          items = items.filter((item) => {
            const ts = new Date(item.ts || '').getTime();
            return !Number.isNaN(ts) && ts >= sinceTime;
          });
        }
      }
      state.items = items;
      state.total = Number(payload.total || 0);
      renderRows(items);
      pageLabelEl.textContent = 'Page ' + String(Math.floor(state.offset / state.limit) + 1);
      prevBtn.disabled = state.offset <= 0;
      nextBtn.disabled = state.offset + state.limit >= state.total;
      statusEl.textContent = items.length ? ('Showing ' + String(items.length) + ' events') : 'No events.';
    }

    tableBody.addEventListener('click', function (e) {
      const link = e.target.closest('[data-event-link]');
      const row = e.target.closest('[data-event-row]');
      if (!link && !row) {
        return;
      }
      e.preventDefault();
      const targetRow = row || link.closest('[data-event-row]');
      if (!targetRow) {
        return;
      }
      const eventId = targetRow.getAttribute('data-event-id');
      if (eventId) {
        openDetail(eventId);
      }
    });
    detailClose.addEventListener('click', function () { detailOverlay.hidden = true; });
    detailOverlay.addEventListener('click', function (e) {
      if (e.target === detailOverlay) {
        detailOverlay.hidden = true;
      }
    });
    prevBtn.addEventListener('click', function () {
      state.offset = Math.max(0, state.offset - state.limit);
      loadPage();
    });
    nextBtn.addEventListener('click', function () {
      state.offset += state.limit;
      loadPage();
    });
    refreshBtn.addEventListener('click', function () {
      loadPage();
    });
    loadPage();
  }

  function initErrorsPage() {
    const tableBody = document.getElementById('errors-table-body');
    if (!tableBody) {
      return;
    }
    const statusEl = document.getElementById('errors-status');
    const pageLabelEl = document.getElementById('errors-page-label');
    const prevBtn = document.getElementById('errors-prev');
    const nextBtn = document.getElementById('errors-next');
    const refreshBtn = document.getElementById('errors-refresh');
    const detailOverlay = document.getElementById('errors-detail-overlay');
    const detailClose = document.getElementById('errors-detail-close');
    const copyBtn = document.getElementById('errors-copy-detail');
    const detailTitle = document.getElementById('errors-detail-title');
    const detailJson = document.getElementById('errors-detail-json');
    const state = { limit: 50, offset: 0, total: 0, items: [], selected: null };

    function renderRows(items) {
      tableBody.innerHTML = '';
      if (!items.length) {
        tableBody.innerHTML = '<tr><td colspan="4">No errors.</td></tr>';
        return;
      }
      items.forEach(function (item) {
        const tr = document.createElement('tr');
        tr.setAttribute('data-error-row', '1');
        tr.setAttribute('data-error-id', String(item.id || ''));
        tr.innerHTML =
          '<td>' + formatLocalDateTime(item.ts) + '</td>' +
          '<td>' + (item.component || '—') + '</td>' +
          '<td>' + (item.message || '—') + '</td>' +
          '<td>' + (item.event_id || '—') + '</td>';
        tableBody.appendChild(tr);
      });
    }

    function openDetail(id) {
      const item = state.items.find((entry) => String(entry.id) === String(id));
      if (!item) {
        return;
      }
      state.selected = item;
      detailTitle.textContent = String(item.component || 'unknown') + ' @ ' + formatLocalDateTime(item.ts);
      detailJson.textContent = JSON.stringify(item, null, 2);
      detailOverlay.hidden = false;
    }

    async function loadPage() {
      const resp = await fetch('/api/errors?limit=' + String(state.limit) + '&offset=' + String(state.offset), {
        credentials: 'same-origin',
      });
      if (!resp.ok) {
        statusEl.textContent = 'Failed loading errors.';
        return;
      }
      const payload = await resp.json();
      const items = Array.isArray(payload.items) ? payload.items : [];
      state.items = items;
      state.total = Number(payload.total || 0);
      renderRows(items);
      pageLabelEl.textContent = 'Page ' + String(Math.floor(state.offset / state.limit) + 1);
      prevBtn.disabled = state.offset <= 0;
      nextBtn.disabled = state.offset + state.limit >= state.total;
      statusEl.textContent = items.length ? ('Showing ' + String(items.length) + ' errors') : 'No errors.';
    }

    tableBody.addEventListener('click', function (e) {
      const row = e.target.closest('[data-error-row]');
      if (!row) {
        return;
      }
      openDetail(row.getAttribute('data-error-id'));
    });
    prevBtn.addEventListener('click', function () {
      state.offset = Math.max(0, state.offset - state.limit);
      loadPage();
    });
    nextBtn.addEventListener('click', function () {
      state.offset += state.limit;
      loadPage();
    });
    refreshBtn.addEventListener('click', function () {
      loadPage();
    });
    detailClose.addEventListener('click', function () { detailOverlay.hidden = true; });
    detailOverlay.addEventListener('click', function (e) {
      if (e.target === detailOverlay) {
        detailOverlay.hidden = true;
      }
    });
    copyBtn.addEventListener('click', async function () {
      if (!state.selected) {
        return;
      }
      try {
        await navigator.clipboard.writeText(JSON.stringify(state.selected, null, 2));
      } catch (err) {
        // ignore
      }
    });
    loadPage();
  }

  function initSetupPage() {
    const container = document.getElementById('setup-cameras');
    if (!container) {
      return;
    }

    const settingKeys = [
      'budget.monthly_limit_usd',
      'policy.defaults.confidence_threshold',
      'policy.modes.doorbell_only',
      'ai.modes.high_precision',
      'ai.defaults.vision_detail',
      'policy.smart_update.phash_threshold_default',
      'policy.smart_update.phash_threshold_update',
      'ui.subtitle',
      'ui.preview_enabled',
      'ui.preview_enabled_interval_s',
      'ui.preview_disabled_interval_s',
      'ui.preview_max_active',
    ];
    const wizard = document.getElementById('camera-setup-wizard');
    const wizardOverlay = document.getElementById('wizard-overlay');
    const globalStatusEl = document.getElementById('settings-status');
    const cameraStatusEl = document.getElementById('camera-save-status');
    const globalDirtyBadge = document.getElementById('unsaved-indicator');
    const cameraDirtyBadge = document.getElementById('camera-unsaved-indicator');
    let serverUnsavedChanges = false;
    const settingsBaseline = {};
    const cameraDirty = {};
    const globalRuntimeValues = Object.assign({}, window.SYNTHIA_SETUP_GLOBALS || {});

    const wizardState = { cameraKey: '', viewId: '', profile: null, currentView: null, currentStep: 1 };

    function qs(id) {
      return document.getElementById(id);
    }

    function fieldValue(id) {
      const input = qs(id);
      if (!input) {
        return '';
      }
      return input.type === 'checkbox' ? input.checked : input.value;
    }

    function normalizeVisionDetail(value) {
      const raw = String(value || '').trim().toLowerCase();
      if (raw === 'high') {
        return 'high';
      }
      if (raw === 'medium') {
        return 'medium';
      }
      return 'low';
    }

    function setFieldValue(id, value) {
      const input = qs(id);
      if (!input) {
        return;
      }
      if (input.type === 'checkbox') {
        input.checked = value === true || value === '1' || String(value).toLowerCase() === 'true';
      } else {
        if (id === 'setting-ai.defaults.vision_detail') {
          input.value = normalizeVisionDetail(value);
          return;
        }
        input.value = value ?? '';
      }
    }

    function collectSettingsPayload() {
      const payload = {};
      settingKeys.forEach((key) => {
        const id = 'setting-' + key;
        if (key === 'ai.defaults.vision_detail') {
          const current = normalizeVisionDetail(fieldValue(id));
          payload[key] = current === 'medium' ? 'low' : current;
          return;
        }
        payload[key] = fieldValue(id);
      });
      return payload;
    }

    function effectiveOverrideLabel(fieldName, inputValue) {
      const value = String(inputValue == null ? '' : inputValue).trim();
      if (value) {
        const rendered = fieldName === 'vision_detail' ? normalizeVisionDetail(value) : value;
        return 'Effective: ' + rendered + ' (override)';
      }
      return '';
    }

    function refreshCardOverrideState(card) {
      ['confidence_threshold', 'cooldown_s', 'vision_detail', 'phash_threshold'].forEach((fieldName) => {
        const input = card.querySelector('[data-field="' + fieldName + '"]');
        if (!input) {
          return;
        }
        const value = String(input.value || '').trim();
        input.classList.toggle('is-override', Boolean(value));
        const tag = card.querySelector('[data-override-tag-for="' + fieldName + '"]');
        if (tag) {
          tag.classList.toggle('is-visible', Boolean(value));
        }
        const effectiveNode = card.querySelector('[data-effective-for="' + fieldName + '"]');
        if (effectiveNode) {
          effectiveNode.textContent = effectiveOverrideLabel(fieldName, value);
        }
      });
    }

    function refreshAllCameraEffectiveValues() {
      container.querySelectorAll('[data-camera-key]').forEach((card) => {
        refreshCardOverrideState(card);
      });
    }

    function refreshGlobalDirtyBadge() {
      let localDirty = false;
      settingKeys.forEach((key) => {
        const current = fieldValue('setting-' + key);
        const baseline = settingsBaseline[key];
        if (String(current) !== String(baseline)) {
          localDirty = true;
        }
      });
      const hasUnsaved = localDirty || serverUnsavedChanges;
      globalDirtyBadge.textContent = hasUnsaved ? 'Unsaved global changes' : 'No unsaved global changes';
      globalDirtyBadge.classList.toggle('warn', hasUnsaved);
    }

    function refreshCameraDirtyBadge() {
      const localDirty = Object.keys(cameraDirty).some((key) => cameraDirty[key]);
      const hasUnsaved = localDirty || serverUnsavedChanges;
      cameraDirtyBadge.textContent = hasUnsaved ? 'Unsaved camera changes' : 'No unsaved camera changes';
      cameraDirtyBadge.classList.toggle('warn', hasUnsaved);
    }

    function wizardSetDeliveryFocus(values) {
      const current = Array.isArray(values) ? values : [];
      ['package', 'food', 'grocery'].forEach((key) => {
        const node = qs('wizard-delivery-focus-' + key);
        if (node) {
          node.checked = current.indexOf(key) >= 0;
        }
      });
    }

    function wizardDeliveryFocusFromInput() {
      if (qs('wizard-profile-purpose').value !== 'doorbell') {
        return [];
      }
      return ['package', 'food', 'grocery'].filter((key) => {
        const node = qs('wizard-delivery-focus-' + key);
        return Boolean(node && node.checked);
      });
    }

    function wizardProfileMissingRequired() {
      const missing = [];
      if (!qs('wizard-profile-environment').value) {
        missing.push('environment');
      }
      if (!qs('wizard-profile-purpose').value) {
        missing.push('purpose');
      }
      if (!qs('wizard-profile-view-type').value) {
        missing.push('view_type');
      }
      if (!String(qs('wizard-profile-mounting-location').value || '').trim()) {
        missing.push('mounting_location');
      }
      return missing;
    }

    function wizardViewPayload() {
      return {
        label: String(qs('wizard-view-label').value || '').trim() || wizardState.viewId,
        ha_preset_id: String(qs('wizard-view-ha-preset-id').value || '').trim() || null,
        context_summary: String(qs('wizard-context-summary').value || '').trim() || null,
        expected_activity: String(qs('wizard-context-activity').value || '').split(',').map((item) => item.trim()).filter(Boolean),
        zones: (function () {
          const raw = String(qs('wizard-context-zones').value || '').trim();
          if (!raw) {
            return [];
          }
          try {
            const parsed = JSON.parse(raw);
            return Array.isArray(parsed) ? parsed : [];
          } catch (err) {
            return [];
          }
        })(),
        focus_notes: String(qs('wizard-context-focus-notes').value || '').trim() || null,
      };
    }

    function wizardProfilePayload() {
      return {
        environment: qs('wizard-profile-environment').value || null,
        purpose: qs('wizard-profile-purpose').value || null,
        view_type: qs('wizard-profile-view-type').value || null,
        mounting_location: String(qs('wizard-profile-mounting-location').value || '').trim() || null,
        view_notes: String(qs('wizard-profile-view-notes').value || '').trim() || null,
        delivery_focus: wizardDeliveryFocusFromInput(),
        default_view_id: String(qs('wizard-profile-default-view-id').value || '').trim() || null,
      };
    }

    function wizardSyncDeliveryFocusVisibility() {
      const wrap = qs('wizard-delivery-focus-wrap');
      if (!wrap) {
        return;
      }
      const enabled = qs('wizard-profile-purpose').value === 'doorbell';
      wrap.style.display = enabled ? '' : 'none';
      if (!enabled) {
        wizardSetDeliveryFocus([]);
      }
    }

    function wizardRefreshDefaultViewOptions(items, fallbackValue) {
      const select = qs('wizard-profile-default-view-id');
      if (!select) {
        return;
      }
      const selectedValue = String(select.value || fallbackValue || '').trim();
      select.innerHTML = '';
      const base = document.createElement('option');
      base.value = '';
      base.textContent = 'default (auto)';
      select.appendChild(base);
      (items || []).forEach((item) => {
        const viewId = String(item.view_id || '').trim();
        if (!viewId) {
          return;
        }
        const opt = document.createElement('option');
        opt.value = viewId;
        opt.textContent = viewId;
        select.appendChild(opt);
      });
      select.value = selectedValue;
    }

    function applyWizardProfile(profile) {
      qs('wizard-profile-environment').value = profile.environment || '';
      qs('wizard-profile-purpose').value = profile.purpose || '';
      qs('wizard-profile-view-type').value = profile.view_type || '';
      qs('wizard-profile-mounting-location').value = profile.mounting_location || '';
      qs('wizard-profile-view-notes').value = profile.view_notes || '';
      wizardSetDeliveryFocus(profile.delivery_focus || []);
      qs('wizard-profile-default-view-id').value = profile.default_view_id || '';
      qs('wizard-profile-privacy-mode').textContent = profile.privacy_mode || 'no_identifying_details';
      qs('wizard-profile-setup-completed').textContent = profile.setup_completed ? 'Completed' : 'Incomplete';
      wizardSyncDeliveryFocusVisibility();
    }

    function applyWizardView(view) {
      qs('wizard-view-id').value = view.view_id || '';
      qs('wizard-view-label').value = view.label || '';
      qs('wizard-view-ha-preset-id').value = view.ha_preset_id || '';
      qs('wizard-snapshot-path').textContent = view.setup_snapshot_path ? ('Snapshot: ' + view.setup_snapshot_path) : 'No setup snapshot captured yet.';
      qs('wizard-context-summary').value = view.context_summary || '';
      qs('wizard-context-activity').value = (view.expected_activity || []).join(',');
      qs('wizard-context-zones').value = JSON.stringify(view.zones || [], null, 2);
      qs('wizard-context-focus-notes').value = view.focus_notes || '';
      qs('wizard-view-meta').textContent = 'Loaded view: ' + (view.view_id || '—');
    }

    function refreshWizardNav() {
      const backBtn = qs('wizard-back-btn');
      const nextBtn = qs('wizard-next-btn');
      const step = wizardState.currentStep;
      backBtn.disabled = step <= 1;
      nextBtn.style.display = step >= 7 ? 'none' : '';
      if (step === 1) {
        nextBtn.disabled = !wizardState.cameraKey;
      } else if (step === 3) {
        nextBtn.disabled = wizardProfileMissingRequired().length > 0;
      } else if (step === 4) {
        nextBtn.disabled = !String(qs('wizard-view-id').value || '').trim();
      } else {
        nextBtn.disabled = false;
      }
    }

    function setWizardStep(step) {
      wizardState.currentStep = Math.max(1, Math.min(7, step));
      Array.from(wizard.querySelectorAll('[data-step-panel]')).forEach((panel) => {
        panel.classList.toggle('is-active', Number(panel.getAttribute('data-step-panel') || '0') === wizardState.currentStep);
      });
      Array.from(wizard.querySelectorAll('[data-step-btn]')).forEach((button) => {
        button.classList.toggle('primary', Number(button.getAttribute('data-step-btn') || '0') === wizardState.currentStep);
      });
      refreshWizardNav();
    }

    async function loadSettings() {
      const resp = await fetch('/api/admin/settings', { credentials: 'same-origin' });
      if (!resp.ok) {
        globalStatusEl.textContent = 'Failed loading global settings.';
        return;
      }
      const data = await resp.json();
      const values = data.runtime || {};
      Object.keys(values).forEach((key) => {
        globalRuntimeValues[key] = values[key];
      });
      settingKeys.forEach((key) => {
        const value = values[key] ?? '';
        setFieldValue('setting-' + key, value);
        settingsBaseline[key] = String(fieldValue('setting-' + key));
      });
      serverUnsavedChanges = Boolean(data.unsaved_changes);
      refreshGlobalDirtyBadge();
      refreshCameraDirtyBadge();
      refreshAllCameraEffectiveValues();
    }

    async function wizardLoadProfile() {
      if (!wizardState.cameraKey) {
        return;
      }
      const resp = await fetch('/api/admin/cameras/' + encodeURIComponent(wizardState.cameraKey) + '/profile', { credentials: 'same-origin' });
      if (!resp.ok) {
        return;
      }
      const profile = await resp.json();
      wizardState.profile = profile;
      applyWizardProfile(profile);
      qs('wizard-camera-meta').textContent = 'Camera: ' + wizardState.cameraKey + ' • env=' + (profile.environment || '—') + ' • purpose=' + (profile.purpose || '—');
      if (!wizardState.viewId) {
        wizardState.viewId = profile.default_view_id || 'default';
      }
      qs('wizard-view-id').value = wizardState.viewId;
      refreshWizardNav();
    }

    async function wizardLoadViews() {
      if (!wizardState.cameraKey) {
        return;
      }
      const resp = await fetch('/api/admin/cameras/' + encodeURIComponent(wizardState.cameraKey) + '/views', { credentials: 'same-origin' });
      if (!resp.ok) {
        return;
      }
      const data = await resp.json();
      const items = data.items || [];
      wizardRefreshDefaultViewOptions(items, wizardState.profile && wizardState.profile.default_view_id);
      if (!wizardState.viewId) {
        wizardState.viewId = items.length ? items[0].view_id : 'default';
        qs('wizard-view-id').value = wizardState.viewId;
      }
      const view = items.find((item) => item.view_id === wizardState.viewId);
      if (view) {
        wizardState.currentView = view;
        applyWizardView(view);
      }
    }

    async function wizardLoadCameras() {
      const select = qs('wizard-camera');
      const resp = await fetch('/api/admin/cameras', { credentials: 'same-origin' });
      if (!resp.ok) {
        qs('wizard-camera-meta').textContent = resp.status === 401 ? 'Admin session expired. Please log in again.' : 'Failed loading cameras for setup.';
        return;
      }
      const data = await resp.json();
      const items = data.items || [];
      select.innerHTML = '';
      items.forEach((camera) => {
        const option = document.createElement('option');
        option.value = camera.camera_key;
        option.textContent = (camera.display_name || camera.camera_key) + ' (' + camera.camera_key + ')';
        select.appendChild(option);
      });
      if (!wizardState.cameraKey && items.length) {
        wizardState.cameraKey = items[0].camera_key;
      }
      select.value = wizardState.cameraKey || (items[0] ? items[0].camera_key : '');
      await wizardLoadProfile();
      await wizardLoadViews();
      await wizardRefreshPreview();
    }

    async function wizardLoadViewById() {
      wizardState.viewId = String(qs('wizard-view-id').value || '').trim() || 'default';
      await wizardLoadViews();
      refreshWizardNav();
    }

    async function wizardSaveView() {
      if (!wizardState.cameraKey) {
        return false;
      }
      wizardState.viewId = String(qs('wizard-view-id').value || '').trim() || 'default';
      const resp = await fetch('/api/admin/cameras/' + encodeURIComponent(wizardState.cameraKey) + '/views/' + encodeURIComponent(wizardState.viewId), {
        method: 'PUT',
        credentials: 'same-origin',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(wizardViewPayload()),
      });
      if (!resp.ok) {
        qs('wizard-view-meta').textContent = 'Failed to save view.';
        return false;
      }
      const view = await resp.json();
      wizardState.currentView = view;
      applyWizardView(view);
      qs('wizard-view-meta').textContent = 'Saved view: ' + wizardState.viewId;
      return true;
    }

    async function wizardRefreshPreview() {
      if (!wizardState.cameraKey) {
        return;
      }
      const img = qs('wizard-preview-image');
      img.src = '/api/cameras/' + encodeURIComponent(wizardState.cameraKey) + '/preview.jpg?ts=' + String(nowTs());
      img.onload = function () {
        qs('wizard-preview-meta').textContent = 'Preview updated.';
      };
      img.onerror = function () {
        qs('wizard-preview-meta').textContent = 'No preview';
      };
    }

    async function wizardCaptureSnapshot() {
      wizardState.viewId = String(qs('wizard-view-id').value || '').trim() || 'default';
      const resp = await fetch('/api/admin/cameras/' + encodeURIComponent(wizardState.cameraKey) + '/views/' + encodeURIComponent(wizardState.viewId) + '/setup/snapshot', {
        method: 'POST',
        credentials: 'same-origin',
      });
      if (!resp.ok) {
        qs('wizard-snapshot-path').textContent = 'Snapshot capture unavailable (coming soon).';
        return;
      }
      const data = await resp.json();
      qs('wizard-snapshot-path').textContent = 'Snapshot: ' + (data.snapshot_path || 'saved');
      if (data.view) {
        applyWizardView(data.view);
      }
    }

    async function wizardGenerateContext() {
      const generateBtn = qs('wizard-generate-context');
      generateBtn.disabled = true;
      const missing = wizardProfileMissingRequired();
      if (missing.length) {
        qs('wizard-save-status').textContent = 'Missing required profile fields: ' + missing.join(', ');
        generateBtn.disabled = false;
        return false;
      }
      wizardState.viewId = String(qs('wizard-view-id').value || '').trim() || 'default';
      const contextPayload = {
        environment: qs('wizard-profile-environment').value || 'outdoor',
        purpose: qs('wizard-profile-purpose').value || 'general',
        view_type: qs('wizard-profile-view-type').value || 'fixed',
        mounting_location: String(qs('wizard-profile-mounting-location').value || '').trim(),
        view_notes: String(qs('wizard-profile-view-notes').value || '').trim() || null,
        delivery_focus: wizardDeliveryFocusFromInput(),
      };
      const resp = await fetch('/api/admin/cameras/' + encodeURIComponent(wizardState.cameraKey) + '/views/' + encodeURIComponent(wizardState.viewId) + '/setup/generate_context', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(contextPayload),
      });
      if (!resp.ok) {
        qs('wizard-save-status').textContent = 'Context generation unavailable (coming soon).';
        generateBtn.disabled = false;
        return false;
      }
      const data = await resp.json();
      if (data.profile) {
        wizardState.profile = data.profile;
        applyWizardProfile(data.profile);
      }
      if (data.view) {
        wizardState.currentView = data.view;
        applyWizardView(data.view);
      }
      qs('wizard-save-status').textContent = 'Context generated.';
      generateBtn.disabled = false;
      return true;
    }

    async function wizardSaveAll() {
      const missing = wizardProfileMissingRequired();
      if (missing.length) {
        qs('wizard-save-status').textContent = 'Missing required profile fields: ' + missing.join(', ');
        return;
      }
      wizardState.viewId = String(qs('wizard-view-id').value || '').trim() || 'default';
      const profileResp = await fetch('/api/admin/cameras/' + encodeURIComponent(wizardState.cameraKey) + '/profile', {
        method: 'PUT',
        credentials: 'same-origin',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(wizardProfilePayload()),
      });
      if (!profileResp.ok) {
        qs('wizard-save-status').textContent = 'Profile save failed.';
        return;
      }
      const savedView = await wizardSaveView();
      if (!savedView) {
        qs('wizard-save-status').textContent = 'View save failed.';
        return;
      }
      qs('wizard-save-status').textContent = 'Setup saved.';
    }

    function payloadFromCameraCard(card) {
      const payload = {};
      card.querySelectorAll('[data-field]').forEach((input) => {
        const key = input.getAttribute('data-field');
        let value = input.type === 'checkbox' ? input.checked : input.value;
        if (key === 'display_name' || key === 'prompt_preset' || key === 'vision_detail') {
          value = String(value).trim();
        }
        if (['confidence_threshold', 'cooldown_s', 'phash_threshold', 'updates_per_event'].indexOf(key) >= 0 && value !== '') {
          value = Number(value);
        }
        if ((key === 'confidence_threshold' || key === 'cooldown_s' || key === 'phash_threshold' || key === 'vision_detail' || key === 'prompt_preset') && value === '') {
          return;
        }
        payload[key] = value;
      });
      return payload;
    }

    function renderCameraCard(camera) {
      const root = document.createElement('div');
      root.className = 'card';
      root.setAttribute('data-camera-key', camera.camera_key);
      const setupLabel = camera.setup_completed ? 'Setup complete' : 'Needs setup';
      const confidenceValue = camera.confidence_threshold === null || camera.confidence_threshold === undefined ? '' : String(camera.confidence_threshold);
      const cooldownValue = camera.cooldown_s === null || camera.cooldown_s === undefined ? '' : String(camera.cooldown_s);
      const phashValue = camera.phash_threshold === null || camera.phash_threshold === undefined ? '' : String(camera.phash_threshold);
      const updatesValue = camera.updates_per_event === null || camera.updates_per_event === undefined ? '' : String(camera.updates_per_event);
      const visionValue = String(camera.vision_detail || '');
      root.innerHTML =
        '<div class="camera-card-head">' +
        '<div class="camera-header-meta"><strong>' + (camera.display_name || camera.camera_key) + '</strong><span class="sub">' + camera.camera_key + ' • ' + setupLabel + '</span></div>' +
        '<label class="toggle"><input type="checkbox" data-field="enabled"' + (camera.enabled ? ' checked' : '') + '><span>Enabled</span></label>' +
        '<span class="pill" data-camera-dirty>Saved</span>' +
        '</div>' +
        '<div class="form-grid camera-override-grid">' +
        '<div class="field-stack"><label class="field-label">Display name</label><input class="field" data-field="display_name" value="' + (camera.display_name || '') + '"></div>' +
        '<div class="field-stack"><label class="field-label">Prompt preset</label><input class="field" data-field="prompt_preset" value="' + (camera.prompt_preset || '') + '"></div>' +
        '<div class="field-stack"><label class="field-label">Updates per event (1 or 2)</label><input class="field" data-field="updates_per_event" value="' + updatesValue + '"></div>' +
        '<div class="field-stack"><label class="field-label">Confidence threshold override <span class="override-tag' + (confidenceValue ? ' is-visible' : '') + '" data-override-tag-for="confidence_threshold">[Override]</span></label><input class="field' + (confidenceValue ? ' is-override' : '') + '" data-field="confidence_threshold" value="' + confidenceValue + '"><div class="field-help">Blank = use global default.</div><div class="field-effective" data-effective-for="confidence_threshold">' + effectiveOverrideLabel('confidence_threshold', confidenceValue) + '</div></div>' +
        '<div class="field-stack"><label class="field-label">Cooldown override seconds <span class="override-tag' + (cooldownValue ? ' is-visible' : '') + '" data-override-tag-for="cooldown_s">[Override]</span></label><input class="field' + (cooldownValue ? ' is-override' : '') + '" data-field="cooldown_s" value="' + cooldownValue + '"><div class="field-help">Blank = use global default.</div><div class="field-effective" data-effective-for="cooldown_s">' + effectiveOverrideLabel('cooldown_s', cooldownValue) + '</div></div>' +
        '<div class="field-stack"><label class="field-label">Vision detail override (blank/low/high) <span class="override-tag' + (visionValue ? ' is-visible' : '') + '" data-override-tag-for="vision_detail">[Override]</span></label><input class="field' + (visionValue ? ' is-override' : '') + '" data-field="vision_detail" value="' + visionValue + '"><div class="field-help">Blank = use global default.</div><div class="field-effective" data-effective-for="vision_detail">' + effectiveOverrideLabel('vision_detail', visionValue) + '</div></div>' +
        '<div class="field-stack"><label class="field-label">pHash threshold override <span class="override-tag' + (phashValue ? ' is-visible' : '') + '" data-override-tag-for="phash_threshold">[Override]</span></label><input class="field' + (phashValue ? ' is-override' : '') + '" data-field="phash_threshold" value="' + phashValue + '"><div class="field-help">Blank = use global default.</div><div class="field-effective" data-effective-for="phash_threshold">' + effectiveOverrideLabel('phash_threshold', phashValue) + '</div></div>' +
        '</div>' +
        '<div class="form-grid camera-secondary-grid">' +
        '<div class="field-stack"><label class="field-label">Guest preview</label><label class="toggle"><input type="checkbox" data-field="guest_preview_enabled"' + (camera.guest_preview_enabled ? ' checked' : '') + '><span>Allow preview image on guest dashboard</span></label></div>' +
        '<div class="field-stack"><label class="field-label">Security capable</label><label class="toggle"><input type="checkbox" data-field="security_capable"' + (camera.security_capable ? ' checked' : '') + '><span>Camera supports security overlay behavior</span></label></div>' +
        '<div class="field-stack"><label class="field-label">Security mode (runtime)</label><label class="toggle"><input type="checkbox" data-field="security_mode"' + (camera.security_mode ? ' checked' : '') + '><span>Enable conservative security overlay prompts</span></label></div>' +
        '</div>' +
        '<div class="row" style="margin-top:10px;">' +
        '<button class="btn" data-action="apply">Apply (runtime)</button>' +
        '<button class="btn primary" data-action="save">Save (persist)</button>' +
        '</div>';
      return root;
    }

    function setCameraCardDirty(card, dirty) {
      const key = card.getAttribute('data-camera-key');
      cameraDirty[key] = Boolean(dirty);
      const badge = card.querySelector('[data-camera-dirty]');
      badge.textContent = dirty ? 'Unsaved' : 'Saved';
      badge.classList.toggle('warn', Boolean(dirty));
      refreshCameraDirtyBadge();
    }

    async function loadCameras() {
      const resp = await fetch('/api/admin/cameras', { credentials: 'same-origin' });
      if (!resp.ok) {
        cameraStatusEl.textContent = 'Failed loading cameras.';
        return;
      }
      const data = await resp.json();
      container.innerHTML = '';
      (data.items || []).forEach((camera) => {
        const card = renderCameraCard(camera);
        container.appendChild(card);
        setCameraCardDirty(card, false);
        card.querySelectorAll('[data-field]').forEach((input) => {
          input.addEventListener('change', function () {
            setCameraCardDirty(card, true);
            refreshCardOverrideState(card);
          });
          input.addEventListener('input', function () {
            setCameraCardDirty(card, true);
            refreshCardOverrideState(card);
          });
        });
        refreshCardOverrideState(card);
        card.querySelector('[data-action="apply"]').addEventListener('click', async function (e) {
          e.preventDefault();
          const payload = payloadFromCameraCard(card);
          const result = await fetch('/api/admin/cameras/' + encodeURIComponent(camera.camera_key) + '/apply', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify(payload),
          });
          if (result.ok) {
            cameraStatusEl.textContent = 'Applied runtime changes for ' + camera.camera_key + '.';
            setCameraCardDirty(card, false);
            serverUnsavedChanges = true;
            refreshGlobalDirtyBadge();
            refreshCameraDirtyBadge();
          } else {
            cameraStatusEl.textContent = 'Failed applying runtime changes.';
          }
        });
        card.querySelector('[data-action="save"]').addEventListener('click', async function (e) {
          e.preventDefault();
          const payload = payloadFromCameraCard(card);
          const result = await fetch('/api/admin/cameras/' + encodeURIComponent(camera.camera_key) + '/save', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify(payload),
          });
          if (result.ok) {
            cameraStatusEl.textContent = 'Saved camera config for ' + camera.camera_key + '.';
            setCameraCardDirty(card, false);
            const savedData = await result.json();
            serverUnsavedChanges = Boolean(savedData.unsaved_changes);
            refreshGlobalDirtyBadge();
            refreshCameraDirtyBadge();
          } else {
            cameraStatusEl.textContent = 'Failed saving camera config.';
          }
        });
      });
      serverUnsavedChanges = Boolean(data.unsaved_changes);
      refreshGlobalDirtyBadge();
      refreshCameraDirtyBadge();
    }

    settingKeys.forEach((key) => {
      const input = qs('setting-' + key);
      if (!input) {
        return;
      }
      input.addEventListener('change', function () {
        refreshGlobalDirtyBadge();
        refreshAllCameraEffectiveValues();
      });
      input.addEventListener('input', function () {
        refreshGlobalDirtyBadge();
        refreshAllCameraEffectiveValues();
      });
    });

    qs('settings-apply').addEventListener('click', async function (e) {
      e.preventDefault();
      const resp = await fetch('/api/admin/settings/apply', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(collectSettingsPayload()),
      });
      if (resp.ok) {
        const data = await resp.json();
        serverUnsavedChanges = Boolean(data.unsaved_changes);
        const runtime = data.runtime || {};
        Object.keys(runtime).forEach((key) => {
          globalRuntimeValues[key] = runtime[key];
        });
        globalStatusEl.textContent = 'Applied runtime settings.';
      } else {
        globalStatusEl.textContent = 'Failed applying runtime settings.';
      }
      refreshGlobalDirtyBadge();
      refreshCameraDirtyBadge();
      refreshAllCameraEffectiveValues();
    });

    qs('settings-save').addEventListener('click', async function (e) {
      e.preventDefault();
      const resp = await fetch('/api/admin/settings/save', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(collectSettingsPayload()),
      });
      if (resp.ok) {
        const data = await resp.json();
        serverUnsavedChanges = Boolean(data.unsaved_changes);
        const runtime = data.runtime || {};
        Object.keys(runtime).forEach((key) => {
          globalRuntimeValues[key] = runtime[key];
        });
        settingKeys.forEach((key) => {
          settingsBaseline[key] = String(fieldValue('setting-' + key));
        });
        globalStatusEl.textContent = 'Saved global settings.';
      } else {
        globalStatusEl.textContent = 'Failed saving global settings.';
      }
      refreshGlobalDirtyBadge();
      refreshCameraDirtyBadge();
      refreshAllCameraEffectiveValues();
    });

    qs('wizard-open-modal').addEventListener('click', function () {
      wizardOverlay.hidden = false;
    });
    qs('wizard-close-modal').addEventListener('click', function () {
      wizardOverlay.hidden = true;
    });
    wizardOverlay.addEventListener('click', function (e) {
      if (e.target === wizardOverlay) {
        wizardOverlay.hidden = true;
      }
    });

    if (wizard) {
      Array.from(wizard.querySelectorAll('[data-step-btn]')).forEach((button) => {
        button.addEventListener('click', function (e) {
          e.preventDefault();
          setWizardStep(Number(button.getAttribute('data-step-btn') || '1'));
        });
      });
      qs('wizard-back-btn').addEventListener('click', function () {
        setWizardStep(wizardState.currentStep - 1);
      });
      qs('wizard-next-btn').addEventListener('click', async function () {
        if (wizardState.currentStep === 4) {
          const saved = await wizardSaveView();
          if (!saved) {
            return;
          }
        }
        if (wizardState.currentStep === 5) {
          await wizardCaptureSnapshot();
        }
        if (wizardState.currentStep === 6) {
          const generated = await wizardGenerateContext();
          if (!generated) {
            return;
          }
        }
        setWizardStep(wizardState.currentStep + 1);
      });
      qs('wizard-camera').addEventListener('change', async function () {
        wizardState.cameraKey = qs('wizard-camera').value;
        wizardState.viewId = '';
        await wizardLoadProfile();
        await wizardLoadViews();
        await wizardRefreshPreview();
        refreshWizardNav();
      });
      qs('wizard-view-load').addEventListener('click', async function (e) { e.preventDefault(); await wizardLoadViewById(); });
      qs('wizard-view-save').addEventListener('click', async function (e) { e.preventDefault(); await wizardSaveView(); });
      qs('wizard-refresh-preview').addEventListener('click', async function (e) { e.preventDefault(); await wizardRefreshPreview(); });
      qs('wizard-capture-snapshot').addEventListener('click', async function (e) { e.preventDefault(); await wizardCaptureSnapshot(); });
      qs('wizard-generate-context').addEventListener('click', async function (e) { e.preventDefault(); await wizardGenerateContext(); });
      qs('wizard-save-all').addEventListener('click', async function (e) { e.preventDefault(); await wizardSaveAll(); });
      ['wizard-profile-environment', 'wizard-profile-purpose', 'wizard-profile-view-type', 'wizard-profile-mounting-location', 'wizard-view-id']
        .forEach(function (id) {
          const node = qs(id);
          if (node) {
            node.addEventListener('change', function () {
              wizardSyncDeliveryFocusVisibility();
              refreshWizardNav();
            });
            node.addEventListener('input', refreshWizardNav);
          }
        });
      wizardSyncDeliveryFocusVisibility();
      setWizardStep(1);
      wizardLoadCameras();
    }

    loadSettings();
    loadCameras();
  }

  document.addEventListener('DOMContentLoaded', async function () {
    initEmbeddedMode();
    const allowed = await guardAdminUiRoute();
    if (!allowed && ['admin', 'setup', 'events', 'errors'].indexOf(document.body.getAttribute('data-ui-page') || '') >= 0) {
      return;
    }
    initGuestTimestamps();
    initGuestKpiRefresh();
    initGuestPreview();
    initAdminPage();
    initSetupPage();
    initEventsPage();
    initErrorsPage();
  });
})();
