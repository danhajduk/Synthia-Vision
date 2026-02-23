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

  function scheduleWithJitter(baseMs) {
    const jitter = Math.floor((Math.random() * 600) - 300);
    return Math.max(500, baseMs + jitter);
  }

  function initGuestPreview() {
    const cfg = window.SYNTHIA_PREVIEW_CONFIG;
    if (!cfg || !cfg.enabled) {
      return;
    }
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
        if (card.getAttribute('data-preview-enabled') !== '1') {
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
        const statusDotEl = card.querySelector('[data-status-dot]');
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
      if (!img) {
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
    const aiCallsEl = document.querySelector('[data-kpi-ai-calls]');
    const avgEventEl = document.querySelector('[data-kpi-avg-event]');

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
      return '$' + asFloat(value, 0).toFixed(2);
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
          heartbeatEl.textContent = statusPayload.timestamp || '—';
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
        if (aiCallsEl) {
          aiCallsEl.textContent = String(asInt(metrics.count_today, 0));
        }
        if (avgEventEl) {
          avgEventEl.textContent = money(metrics.cost_avg_per_event);
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

    function fieldValue(id) {
      const input = document.getElementById(id);
      if (!input) {
        return '';
      }
      if (input.type === 'checkbox') {
        return input.checked;
      }
      return input.value;
    }

    function setFieldValue(id, value) {
      const input = document.getElementById(id);
      if (!input) {
        return;
      }
      if (input.type === 'checkbox') {
        input.checked = value === true || value === '1' || String(value).toLowerCase() === 'true';
        return;
      }
      input.value = value ?? '';
    }

    function collectSettingsPayload() {
      const payload = {};
      settingKeys.forEach((key) => {
        payload[key] = fieldValue('setting-' + key);
      });
      return payload;
    }

    function setUnsavedIndicator(hasUnsaved) {
      const badge = document.getElementById('unsaved-indicator');
      if (!badge) {
        return;
      }
      badge.textContent = hasUnsaved ? 'Unsaved runtime changes' : 'No runtime-only changes';
      badge.classList.toggle('warn', hasUnsaved);
    }

    async function loadSettings() {
      const resp = await fetch('/api/admin/settings', { credentials: 'same-origin' });
      if (!resp.ok) {
        return;
      }
      const data = await resp.json();
      const values = data.runtime || {};
      settingKeys.forEach((key) => {
        setFieldValue('setting-' + key, values[key] ?? '');
      });
      setUnsavedIndicator(Boolean(data.unsaved_changes));
    }

    function cameraCard(camera) {
      const root = document.createElement('div');
      root.className = 'card';
      const confidenceValue =
        camera.confidence_threshold === null || camera.confidence_threshold === undefined
          ? ''
          : String(camera.confidence_threshold);
      const cooldownValue =
        camera.cooldown_s === null || camera.cooldown_s === undefined ? '' : String(camera.cooldown_s);
      const phashValue =
        camera.phash_threshold === null || camera.phash_threshold === undefined
          ? ''
          : String(camera.phash_threshold);
      const updatesValue =
        camera.updates_per_event === null || camera.updates_per_event === undefined
          ? ''
          : String(camera.updates_per_event);
      root.innerHTML =
        '<div class="row"><strong>' + (camera.display_name || camera.camera_key) + '</strong><span class="sub">' + camera.camera_key + '</span></div>' +
        '<div class="form-grid" style="margin-top:10px;">' +
        '<label class="field-label">Display name</label><input class="field" data-field="display_name" value="' + (camera.display_name || '') + '">' +
        '<label class="field-label">Enabled</label><label class="toggle"><input type="checkbox" data-field="enabled"' + (camera.enabled ? ' checked' : '') + '><span>Process events for this camera</span></label>' +
        '<label class="field-label">Prompt preset</label><input class="field" data-field="prompt_preset" value="' + (camera.prompt_preset || '') + '">' +
        '<label class="field-label">Confidence threshold override (blank = global)</label><input class="field" data-field="confidence_threshold" value="' + confidenceValue + '">' +
        '<label class="field-label">Cooldown override seconds (blank = global)</label><input class="field" data-field="cooldown_s" value="' + cooldownValue + '">' +
        '<label class="field-label">Vision detail override (blank/low/high)</label><input class="field" data-field="vision_detail" value="' + (camera.vision_detail || '') + '">' +
        '<label class="field-label">pHash threshold override (blank = global)</label><input class="field" data-field="phash_threshold" value="' + phashValue + '">' +
        '<label class="field-label">Updates per event (1 or 2)</label><input class="field" data-field="updates_per_event" value="' + updatesValue + '">' +
        '<label class="field-label">Guest preview</label><label class="toggle"><input type="checkbox" data-field="guest_preview_enabled"' + (camera.guest_preview_enabled ? ' checked' : '') + '><span>Allow preview image on guest dashboard</span></label>' +
        '</div>' +
        '<div class="row" style="margin-top:10px;">' +
        '<button class="btn" data-action="apply">Apply (runtime)</button>' +
        '<button class="btn primary" data-action="save">Save (persist)</button>' +
        '</div>';
      return root;
    }

    function payloadFromCameraCard(card) {
      const payload = {};
      card.querySelectorAll('[data-field]').forEach((input) => {
        const key = input.getAttribute('data-field');
        let value;
        if (input.type === 'checkbox') {
          value = input.checked;
        } else {
          value = input.value;
        }
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

    async function loadCameras() {
      const resp = await fetch('/api/admin/cameras', { credentials: 'same-origin' });
      if (!resp.ok) {
        return;
      }
      const data = await resp.json();
      container.innerHTML = '';
      (data.items || []).forEach((camera) => {
        const card = cameraCard(camera);
        container.appendChild(card);
        card.querySelector('[data-action="apply"]').addEventListener('click', async function (e) {
          e.preventDefault();
          const payload = payloadFromCameraCard(card);
          await fetch('/api/admin/cameras/' + encodeURIComponent(camera.camera_key) + '/apply', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify(payload),
          });
          setUnsavedIndicator(true);
          await loadCameras();
        });
        card.querySelector('[data-action="save"]').addEventListener('click', async function (e) {
          e.preventDefault();
          const payload = payloadFromCameraCard(card);
          const saveResp = await fetch('/api/admin/cameras/' + encodeURIComponent(camera.camera_key) + '/save', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify(payload),
          });
          if (saveResp.ok) {
            setUnsavedIndicator(false);
          }
          await loadCameras();
        });
      });
      setUnsavedIndicator(Boolean(data.unsaved_changes));
    }

    document.getElementById('settings-apply').addEventListener('click', async function (e) {
      e.preventDefault();
      const resp = await fetch('/api/admin/settings/apply', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(collectSettingsPayload()),
      });
      if (resp.ok) {
        const data = await resp.json();
        setUnsavedIndicator(Boolean(data.unsaved_changes));
      }
    });

    document.getElementById('settings-save').addEventListener('click', async function (e) {
      e.preventDefault();
      const resp = await fetch('/api/admin/settings/save', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(collectSettingsPayload()),
      });
      if (resp.ok) {
        const data = await resp.json();
        setUnsavedIndicator(Boolean(data.unsaved_changes));
      }
    });

    loadSettings();
    loadCameras();
  }

  document.addEventListener('DOMContentLoaded', function () {
    initEmbeddedMode();
    initGuestTimestamps();
    initGuestKpiRefresh();
    initGuestPreview();
    initSetupPage();
  });
})();
