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
    const wizardState = {
      cameraKey: '',
      viewId: '',
      profile: null,
      currentView: null,
      currentStep: 1,
    };

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

    function qs(id) {
      return document.getElementById(id);
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

    function wizardSetDeliveryFocus(values) {
      const current = Array.isArray(values) ? values : [];
      ['package', 'food', 'grocery'].forEach((key) => {
        const node = qs('wizard-delivery-focus-' + key);
        if (!node) {
          return;
        }
        node.checked = current.indexOf(key) >= 0;
      });
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
        expected_activity: String(qs('wizard-context-activity').value || '')
          .split(',')
          .map((item) => item.trim())
          .filter((item) => Boolean(item)),
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
      qs('wizard-snapshot-path').textContent = view.setup_snapshot_path
        ? 'Snapshot: ' + view.setup_snapshot_path
        : 'No setup snapshot captured yet.';
      qs('wizard-context-summary').value = view.context_summary || '';
      qs('wizard-context-activity').value = (view.expected_activity || []).join(',');
      qs('wizard-context-zones').value = JSON.stringify(view.zones || [], null, 2);
      qs('wizard-context-focus-notes').value = view.focus_notes || '';
      qs('wizard-view-meta').textContent = 'Loaded view: ' + (view.view_id || '—');
    }

    function setWizardStep(step) {
      wizardState.currentStep = step;
      Array.from(wizard.querySelectorAll('[data-step-panel]')).forEach((panel) => {
        const panelStep = Number(panel.getAttribute('data-step-panel') || '0');
        panel.classList.toggle('is-active', panelStep === step);
      });
      Array.from(wizard.querySelectorAll('[data-step-btn]')).forEach((button) => {
        const buttonStep = Number(button.getAttribute('data-step-btn') || '0');
        button.classList.toggle('primary', buttonStep === step);
      });
    }

    async function wizardLoadCameras() {
      const select = qs('wizard-camera');
      const resp = await fetch('/api/admin/cameras', { credentials: 'same-origin' });
      if (!resp.ok) {
        const meta = qs('wizard-camera-meta');
        if (meta) {
          meta.textContent = resp.status === 401
            ? 'Admin session expired. Please log in again.'
            : 'Failed loading cameras for setup.';
        }
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

    async function wizardLoadProfile() {
      if (!wizardState.cameraKey) {
        return;
      }
      const resp = await fetch('/api/admin/cameras/' + encodeURIComponent(wizardState.cameraKey) + '/profile', {
        credentials: 'same-origin',
      });
      if (!resp.ok) {
        return;
      }
      const profile = await resp.json();
      wizardState.profile = profile;
      applyWizardProfile(profile);
      qs('wizard-camera-meta').textContent =
        'Camera: ' + wizardState.cameraKey +
        ' • env=' + (profile.environment || '—') +
        ' • purpose=' + (profile.purpose || '—');
      if (!wizardState.viewId) {
        wizardState.viewId = profile.default_view_id || 'default';
      }
      qs('wizard-view-id').value = wizardState.viewId;
    }

    async function wizardLoadViews() {
      if (!wizardState.cameraKey) {
        return;
      }
      const resp = await fetch('/api/admin/cameras/' + encodeURIComponent(wizardState.cameraKey) + '/views', {
        credentials: 'same-origin',
      });
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

    async function wizardLoadViewById() {
      if (!wizardState.cameraKey) {
        return;
      }
      wizardState.viewId = String(qs('wizard-view-id').value || '').trim() || 'default';
      const resp = await fetch(
        '/api/admin/cameras/' + encodeURIComponent(wizardState.cameraKey) + '/views',
        { credentials: 'same-origin' }
      );
      if (!resp.ok) {
        return;
      }
      const data = await resp.json();
      const items = data.items || [];
      wizardRefreshDefaultViewOptions(items, qs('wizard-profile-default-view-id').value);
      const view = items.find((item) => item.view_id === wizardState.viewId);
      if (view) {
        wizardState.currentView = view;
        applyWizardView(view);
      } else {
        qs('wizard-view-label').value = wizardState.viewId;
        qs('wizard-view-ha-preset-id').value = '';
        qs('wizard-view-meta').textContent = 'View not found. New view will be created on save.';
      }
    }

    async function wizardSaveView() {
      if (!wizardState.cameraKey) {
        return;
      }
      wizardState.viewId = String(qs('wizard-view-id').value || '').trim() || 'default';
      const payload = wizardViewPayload();
      const resp = await fetch(
        '/api/admin/cameras/' + encodeURIComponent(wizardState.cameraKey) + '/views/' + encodeURIComponent(wizardState.viewId),
        {
          method: 'PUT',
          credentials: 'same-origin',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify(payload),
        }
      );
      if (!resp.ok) {
        qs('wizard-view-meta').textContent = 'Failed to save view.';
        return;
      }
      const view = await resp.json();
      wizardState.currentView = view;
      applyWizardView(view);
      qs('wizard-view-meta').textContent = 'Saved view: ' + wizardState.viewId;
      await wizardLoadViews();
    }

    async function wizardRefreshPreview() {
      if (!wizardState.cameraKey) {
        return;
      }
      const img = qs('wizard-preview-image');
      img.src = '/api/cameras/' + encodeURIComponent(wizardState.cameraKey) + '/preview.jpg?ts=' + String(nowTs());
    }

    async function wizardCaptureSnapshot() {
      if (!wizardState.cameraKey) {
        return;
      }
      wizardState.viewId = String(qs('wizard-view-id').value || '').trim() || 'default';
      const resp = await fetch(
        '/api/admin/cameras/' + encodeURIComponent(wizardState.cameraKey) + '/views/' +
          encodeURIComponent(wizardState.viewId) + '/setup/snapshot',
        {
          method: 'POST',
          credentials: 'same-origin',
        }
      );
      if (!resp.ok) {
        let detail = '';
        try {
          const payload = await resp.json();
          detail = payload && payload.detail ? String(payload.detail) : '';
        } catch (err) {
          detail = '';
        }
        qs('wizard-snapshot-path').textContent = detail
          ? 'Failed capturing setup snapshot: ' + detail
          : 'Failed capturing setup snapshot.';
        return;
      }
      const data = await resp.json();
      qs('wizard-snapshot-path').textContent = 'Snapshot: ' + (data.snapshot_path || 'saved');
      if (data.view) {
        wizardState.currentView = data.view;
        applyWizardView(data.view);
      }
      await wizardRefreshPreview();
    }

    async function wizardGenerateContext() {
      if (!wizardState.cameraKey) {
        qs('wizard-save-status').textContent = 'No camera selected. Reload setup or log in again.';
        return;
      }
      const generateBtn = qs('wizard-generate-context');
      const statusEl = qs('wizard-save-status');
      if (generateBtn) {
        generateBtn.disabled = true;
        generateBtn.textContent = 'Generating...';
      }
      if (statusEl) {
        statusEl.textContent = 'Generating context...';
      }
      const missing = wizardProfileMissingRequired();
      if (missing.length) {
        if (statusEl) {
          statusEl.textContent = 'Missing required profile fields: ' + missing.join(', ');
        }
        if (generateBtn) {
          generateBtn.disabled = false;
          generateBtn.textContent = 'Generate context';
        }
        return;
      }
      wizardState.viewId = String(qs('wizard-view-id').value || '').trim() || 'default';
      const payload = {
        environment: qs('wizard-profile-environment').value || 'outdoor',
        purpose: qs('wizard-profile-purpose').value || 'general',
        view_type: qs('wizard-profile-view-type').value || 'fixed',
        mounting_location: String(qs('wizard-profile-mounting-location').value || '').trim(),
        view_notes: String(qs('wizard-profile-view-notes').value || '').trim() || null,
        delivery_focus: wizardDeliveryFocusFromInput(),
      };
      try {
        const resp = await fetch(
          '/api/admin/cameras/' + encodeURIComponent(wizardState.cameraKey) + '/views/' +
            encodeURIComponent(wizardState.viewId) + '/setup/generate_context',
          {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify(payload),
          }
        );
        if (!resp.ok) {
          let detail = '';
          try {
            const payload = await resp.json();
            detail = payload && payload.detail ? String(payload.detail) : '';
          } catch (err) {
            detail = '';
          }
          qs('wizard-save-status').textContent = detail
            ? ('Context generation failed: ' + detail)
            : 'Context generation failed.';
          return;
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
      } catch (err) {
        qs('wizard-save-status').textContent =
          'Context generation failed: ' + (err && err.message ? err.message : 'network error');
      } finally {
        if (generateBtn) {
          generateBtn.disabled = false;
          generateBtn.textContent = 'Generate context';
        }
      }
    }

    async function wizardSaveAll() {
      if (!wizardState.cameraKey) {
        return;
      }
      const missing = wizardProfileMissingRequired();
      if (missing.length) {
        qs('wizard-save-status').textContent =
          'Missing required profile fields: ' + missing.join(', ');
        return;
      }
      wizardState.viewId = String(qs('wizard-view-id').value || '').trim() || 'default';
      const profileResp = await fetch(
        '/api/admin/cameras/' + encodeURIComponent(wizardState.cameraKey) + '/profile',
        {
          method: 'PUT',
          credentials: 'same-origin',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify(wizardProfilePayload()),
        }
      );
      if (!profileResp.ok) {
        qs('wizard-save-status').textContent = 'Profile save failed.';
        return;
      }
      await wizardSaveView();
      const profile = await profileResp.json();
      wizardState.profile = profile;
      qs('wizard-save-status').textContent = 'Setup saved.';
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
        '<label class="field-label">Security capable</label><label class="toggle"><input type="checkbox" data-field="security_capable"' + (camera.security_capable ? ' checked' : '') + '><span>Camera supports security overlay behavior</span></label>' +
        '<label class="field-label">Security mode (runtime)</label><label class="toggle"><input type="checkbox" data-field="security_mode"' + (camera.security_mode ? ' checked' : '') + '><span>Enable conservative security overlay prompts</span></label>' +
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

    if (wizard) {
      Array.from(wizard.querySelectorAll('[data-step-btn]')).forEach((button) => {
        button.addEventListener('click', function (e) {
          e.preventDefault();
          const step = Number(button.getAttribute('data-step-btn') || '1');
          setWizardStep(step);
        });
      });
      qs('wizard-camera').addEventListener('change', async function () {
        wizardState.cameraKey = qs('wizard-camera').value;
        wizardState.viewId = '';
        await wizardLoadProfile();
        await wizardLoadViews();
        await wizardRefreshPreview();
      });
      qs('wizard-view-load').addEventListener('click', async function (e) {
        e.preventDefault();
        await wizardLoadViewById();
      });
      qs('wizard-view-save').addEventListener('click', async function (e) {
        e.preventDefault();
        await wizardSaveView();
      });
      qs('wizard-profile-purpose').addEventListener('change', function () {
        wizardSyncDeliveryFocusVisibility();
      });
      qs('wizard-refresh-preview').addEventListener('click', async function (e) {
        e.preventDefault();
        await wizardRefreshPreview();
      });
      qs('wizard-capture-snapshot').addEventListener('click', async function (e) {
        e.preventDefault();
        await wizardCaptureSnapshot();
      });
      qs('wizard-generate-context').addEventListener('click', async function (e) {
        e.preventDefault();
        await wizardGenerateContext();
      });
      qs('wizard-save-all').addEventListener('click', async function (e) {
        e.preventDefault();
        await wizardSaveAll();
      });
      wizardSyncDeliveryFocusVisibility();
      setWizardStep(1);
      wizardLoadCameras();
    }

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
