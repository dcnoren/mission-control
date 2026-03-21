// Mission Control - WebSocket Client & UI Logic

const THEME_VISUALS = {
    mission_control: {
        primary: '56, 189, 247',
        glow: '56, 189, 247',
        gradientStart: '5, 10, 31',
        gradientEnd: '10, 15, 26',
    },
    bluey: {
        primary: '242, 153, 51',
        glow: '242, 217, 102',
        gradientStart: '26, 64, 77',
        gradientEnd: '13, 38, 77',
    },
    snoop_and_sniffy: {
        primary: '230, 179, 77',
        glow: '230, 191, 89',
        gradientStart: '38, 26, 15',
        gradientEnd: '26, 26, 26',
    },
};

const App = {
    ws: null,
    connected: false,
    screen: 'setup', // setup, game, results
    gameState: {
        running: false,
        currentRound: 0,
        totalRounds: 0,
        completedCount: 0,
        totalTime: 0,
        results: [],
        challenge: null,
        elapsed: 0,
    },
    selectedTheme: 'mission_control',
    currentThemeSlug: null,
    appleTVMode: false,
    fetchedEntities: null,
    fetchedSpeakers: null,
    floors: [],
    allowedSpeakers: [],

    init() {
        this.bindEvents();
        this.connectWS();
        this.selectTheme('mission_control');
        this.loadConfig().then(() => this.populateSpeakerDropdowns());
        this.loadChallenges();
        this.loadBlacklist();
        this.loadIntroMusic();
        this.loadSceneImages();
        this.loadThemePhrases();
    },

    // --- Config ---
    async loadConfig() {
        try {
            const resp = await fetch('/api/config');
            const config = await resp.json();

            if (config.ha_url) {
                document.getElementById('input-ha-url').value = config.ha_url;
            }
            if (config.hub_speaker) {
                const hubEl = document.getElementById('input-hub-speaker-select');
                if (hubEl) hubEl.value = config.hub_speaker;
            }
            if (config.server_url) {
                document.getElementById('input-server-url').value = config.server_url;
            }
            const cacheEl = document.getElementById('cache-status');
            if (cacheEl && config.cached_audio_files !== undefined) {
                cacheEl.textContent = `Audio cache: ${config.cached_audio_files} files`;
            }

            this.allowedSpeakers = config.allowed_speakers || [];
            this.floors = config.floors || [];

            const volumePct = Math.round((config.speaker_volume ?? 0.40) * 100);
            document.getElementById('input-speaker-volume').value = volumePct;
            document.getElementById('volume-display').textContent = volumePct + '%';
            this.renderFloorConfig();
            this.renderFloorCheckboxes();

            // Show set/unset status for secret fields
            this.updateSecretStatus('status-ha-token', config.ha_token_set);
            this.updateSecretStatus('status-elevenlabs-key', config.elevenlabs_api_key_set);
            this.updateSecretStatus('status-openrouter-key', config.openrouter_api_key_set);
        } catch (err) {
            console.error('Failed to load config:', err);
        }
    },

    updateSecretStatus(elementId, isSet) {
        const el = document.getElementById(elementId);
        if (!el) return;
        if (isSet) {
            el.textContent = 'Configured';
            el.className = 'field-status set';
        } else {
            el.textContent = 'Not set';
            el.className = 'field-status unset';
        }
    },

    async saveConfig() {
        const btn = document.getElementById('btn-save-config');
        btn.disabled = true;
        btn.textContent = 'Saving...';

        const body = {};

        const haUrl = document.getElementById('input-ha-url').value.trim();
        if (haUrl) body.ha_url = haUrl;

        const haToken = document.getElementById('input-ha-token').value.trim();
        if (haToken) body.ha_token = haToken;

        const elevenlabsKey = document.getElementById('input-elevenlabs-key').value.trim();
        if (elevenlabsKey) body.elevenlabs_api_key = elevenlabsKey;

        const openrouterKey = document.getElementById('input-openrouter-key').value.trim();
        if (openrouterKey) body.openrouter_api_key = openrouterKey;

        const hubSpeaker = document.getElementById('input-hub-speaker-select').value;
        if (hubSpeaker) body.hub_speaker = hubSpeaker;

        const serverUrl = document.getElementById('input-server-url').value.trim();
        if (serverUrl) body.server_url = serverUrl;

        const volumeSlider = document.getElementById('input-speaker-volume');
        body.speaker_volume = parseInt(volumeSlider.value, 10) / 100;

        try {
            const resp = await fetch('/api/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            const data = await resp.json();
            if (data.status === 'saved') {
                // Clear password fields after save
                document.getElementById('input-ha-token').value = '';
                document.getElementById('input-elevenlabs-key').value = '';
                document.getElementById('input-openrouter-key').value = '';
                // Refresh status indicators
                await this.loadConfig();
            }
        } catch (err) {
            alert('Failed to save config: ' + err.message);
        } finally {
            btn.disabled = false;
            btn.textContent = 'Save Settings';
        }
    },

    // --- Speakers ---
    async discoverSpeakers() {
        const btn = document.getElementById('btn-discover-speakers');
        const status = document.getElementById('speaker-status');
        btn.disabled = true;
        btn.textContent = 'Scanning...';
        status.textContent = '';

        try {
            const resp = await fetch('/api/ha/speakers');
            if (!resp.ok) {
                const err = await resp.json();
                status.textContent = 'Error: ' + (err.error || 'Failed');
                return;
            }

            const allSpeakers = await resp.json();
            if (!allSpeakers.length) {
                status.textContent = 'No speakers found in Home Assistant.';
                return;
            }

            // Get currently allowed speakers
            const configResp = await fetch('/api/config');
            const config = await configResp.json();
            const allowed = new Set((config.allowed_speakers || []).map(s => s.entity_id));

            status.textContent = `Found ${allSpeakers.length} speakers. Toggle which ones to use.`;

            const list = document.getElementById('speaker-list');
            list.innerHTML = allSpeakers.map(s => {
                const isAllowed = allowed.has(s.entity_id);
                return `
                    <div class="speaker-item">
                        <label class="toggle-label">
                            <input type="checkbox" class="speaker-toggle" data-entity="${s.entity_id}" data-name="${s.friendly_name}" data-area="${s.area}" ${isAllowed ? 'checked' : ''}>
                            <span class="toggle-slider"></span>
                            <div class="speaker-item-details">
                                <span class="speaker-item-name">${s.friendly_name}</span>
                                <span class="speaker-item-entity">${s.entity_id}</span>
                            </div>
                            <span class="speaker-item-area">${s.area}</span>
                        </label>
                    </div>
                `;
            }).join('') + `
                <button class="btn btn-secondary" style="margin-top:12px" onclick="App.saveAllowedSpeakers()">Save Speaker Selection</button>
            `;
        } catch (err) {
            status.textContent = 'Error: ' + err.message;
        } finally {
            btn.disabled = false;
            btn.textContent = 'Discover Speakers';
        }
    },

    async saveAllowedSpeakers() {
        const toggles = document.querySelectorAll('.speaker-toggle:checked');
        const allowed = Array.from(toggles).map(t => ({
            entity_id: t.dataset.entity,
            friendly_name: t.dataset.name,
            area: t.dataset.area,
        }));

        if (!allowed.length) {
            alert('Select at least one speaker.');
            return;
        }

        try {
            const resp = await fetch('/api/speakers/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ allowed_speakers: allowed }),
            });
            if (resp.ok) {
                const status = document.getElementById('speaker-status');
                status.textContent = `Saved ${allowed.length} speakers`;
                setTimeout(() => status.textContent = '', 2000);
                this.allowedSpeakers = allowed;
                this.populateSpeakerDropdowns();
                this.renderFloorConfig();
                this.renderFloorCheckboxes();
            }
        } catch (err) {
            console.error('Save speakers failed:', err);
        }
    },

    async populateSpeakerDropdowns() {
        try {
            const resp = await fetch('/api/config');
            const config = await resp.json();
            const allowed = config.allowed_speakers || [];
            const savedHub = config.hub_speaker || '';

            const banner = document.getElementById('setup-required-banner');
            const content = document.getElementById('launch-content');

            if (!allowed.length) {
                // No speakers configured — show banner, disable launch
                if (banner) banner.style.display = 'flex';
                document.getElementById('btn-launch').disabled = true;
                document.getElementById('btn-launch-atv').disabled = true;
                return;
            }

            if (banner) banner.style.display = 'none';
            document.getElementById('btn-launch').disabled = false;
            document.getElementById('btn-launch-atv').disabled = false;

            // Populate hub speaker dropdown from allowed list
            const hubSelect = document.getElementById('input-hub-speaker-select');
            hubSelect.innerHTML = allowed.map(s =>
                `<option value="${s.entity_id}" ${s.entity_id === savedHub ? 'selected' : ''}>${s.friendly_name} (${s.area})</option>`
            ).join('');
            hubSelect.onchange = () => {
                fetch('/api/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ hub_speaker: hubSelect.value }),
                });
            };

            // Populate test speaker dropdown
            const testSelect = document.getElementById('input-test-speaker');
            testSelect.innerHTML = allowed.map(s =>
                `<option value="${s.entity_id}">${s.friendly_name} (${s.area})</option>`
            ).join('');
        } catch (err) {
            console.error('Failed to populate speaker dropdowns:', err);
        }
    },

    switchTab(tabId) {
        document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
        document.querySelector(`.tab[data-tab="${tabId}"]`).classList.add('active');
        document.getElementById(tabId).classList.add('active');
    },

    // --- WebSocket ---
    connectWS() {
        const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
        this.ws = new WebSocket(`${protocol}//${location.host}/ws`);

        this.ws.onopen = () => {
            this.connected = true;
            this.updateConnectionStatus();
        };

        this.ws.onclose = () => {
            this.connected = false;
            this.updateConnectionStatus();
            setTimeout(() => this.connectWS(), 3000);
        };

        this.ws.onerror = () => {
            this.connected = false;
            this.updateConnectionStatus();
        };

        this.ws.onmessage = (e) => {
            try {
                const data = JSON.parse(e.data);
                this.handleEvent(data);
            } catch (err) {
                console.error('WS parse error:', err);
            }
        };
    },

    handleEvent(data) {
        switch (data.type) {
            case 'state_sync':
                if (data.running) {
                    const results = data.results || [];
                    const completed = results.filter(r => r.status === 'completed');
                    this.gameState.running = true;
                    this.gameState.currentRound = data.current_round;
                    this.gameState.totalRounds = data.total_rounds;
                    this.gameState.results = results;
                    this.gameState.completedCount = completed.length;
                    this.gameState.totalTime = completed.reduce((sum, r) => sum + r.time, 0);
                    this.showScreen('game');
                    this.updateScoreBar();
                    this.showWaiting('Reconnected. Waiting for next event...');
                }
                break;

            case 'game_starting':
                this.gameState = {
                    running: true,
                    currentRound: 0,
                    totalRounds: data.rounds,
                    completedCount: 0,
                    totalTime: 0,
                    results: [],
                    challenge: null,
                    elapsed: 0,
                };
                this.currentThemeSlug = data.theme_slug || this.selectedTheme;
                this.applyThemeVisuals(this.currentThemeSlug);
                this.setBackgroundImage(data.intro_image_url || null);
                this.showScreen('game');
                this.showWaiting('Starting game...');
                break;

            case 'precaching':
                if (this.screen !== 'game') {
                    this.gameState = { running: true, currentRound: 0, totalRounds: 0, completedCount: 0, totalTime: 0, results: [], challenge: null, elapsed: 0 };
                    this.currentThemeSlug = this.selectedTheme;
                    this.applyThemeVisuals(this.currentThemeSlug);
                    this.showScreen('game');
                }
                this.showWaiting(data.message || `Caching audio: ${data.cached || 0} cached, ${data.to_generate || '?'} to generate...`);
                break;

            case 'precaching_progress':
                this.showWaiting(`Generating audio: ${data.generated} / ${data.total}...`);
                break;

            case 'precaching_done':
                this.showWaiting('Game starting...');
                break;

            case 'game_started':
                this.gameState.totalRounds = data.total_rounds;
                if (!this.currentThemeSlug) {
                    this.currentThemeSlug = this.selectedTheme;
                    this.applyThemeVisuals(this.currentThemeSlug);
                }
                if (this.screen !== 'game') this.showScreen('game');
                this.showWaiting('Here we go!');
                break;

            case 'round_starting':
                this.gameState.currentRound = data.round;
                this.gameState.totalRounds = data.total_rounds;
                this.gameState.challenge = data.challenge;
                this.gameState.elapsed = 0;
                this.setBackgroundImage(data.scene_image_url || null);
                document.getElementById('btn-advance').style.display = 'none';
                this.renderGameScreen();
                break;

            case 'timer_tick':
                this.gameState.elapsed = data.elapsed;
                this.updateTimer();
                break;

            case 'target_update':
                this.updateTargets(data.targets);
                break;

            case 'round_complete':
            case 'round_skipped':
                this.gameState.results.push(data);
                if (data.status === 'completed') {
                    this.gameState.completedCount++;
                    this.gameState.totalTime += data.time;
                    this.updateScoreBar();
                    this.showRoundComplete(data.challenge_name, data.time);
                    this.spawnConfetti();
                } else {
                    this.updateScoreBar();
                    this.showWaiting('Next round coming up...');
                }
                break;

            case 'finale':
                if (data.outro_image_url) {
                    this.setBackgroundImage(data.outro_image_url);
                }
                this.showFinale(data.completed, data.total_rounds);
                this.spawnConfetti();
                break;

            case 'game_finished':
                this.gameState.running = false;
                this.gameState.results = data.results;
                this.gameState.totalTime = data.total_time;
                this.gameState.completedCount = data.completed;
                this.clearGameVisuals();
                this.showResults();
                break;

            case 'game_stopped':
                this.gameState.running = false;
                this.gameState.results = data.results || [];
                this.clearGameVisuals();
                this.showResults();
                break;

            case 'atv_waiting_for_advance':
                if (data.transition_image_url) {
                    this.setBackgroundImage(data.transition_image_url);
                }
                document.getElementById('btn-advance').style.display = 'block';
                this.showWaiting('Round complete! Press Next Mission when ready.');
                break;

            case 'atv_connected':
                console.log('Apple TV connected');
                break;

            case 'atv_error':
                console.error('Apple TV error:', data.message);
                break;

            case 'error':
                alert('Game error: ' + data.message);
                this.showScreen('setup');
                break;
        }
    },

    // --- UI Binding ---
    bindEvents() {
        document.querySelectorAll('.theme-card').forEach(card => {
            card.addEventListener('click', () => this.selectTheme(card.dataset.theme));
        });

        document.getElementById('btn-launch').addEventListener('click', () => this.startGame());
        document.getElementById('btn-launch-atv').addEventListener('click', () => this.startGameATV());

        // Split-button dropdowns
        document.getElementById('btn-launch-dropdown').addEventListener('click', (e) => {
            e.stopPropagation();
            this.toggleDropdown('launch-dropdown-menu');
        });
        document.getElementById('btn-launch-atv-dropdown').addEventListener('click', (e) => {
            e.stopPropagation();
            this.toggleDropdown('launch-atv-dropdown-menu');
        });
        document.getElementById('btn-review-launch').addEventListener('click', () => {
            this.closeDropdowns();
            this.reviewAndLaunch(false);
        });
        document.getElementById('btn-review-launch-atv').addEventListener('click', () => {
            this.closeDropdowns();
            this.reviewAndLaunch(true);
        });
        document.getElementById('btn-confirm-launch').addEventListener('click', () => this.confirmReviewLaunch());
        document.getElementById('btn-cancel-review').addEventListener('click', () => this.cancelReview());
        document.addEventListener('click', () => this.closeDropdowns());
        document.getElementById('btn-skip').addEventListener('click', () => this.skipRound());
        document.getElementById('btn-stop').addEventListener('click', () => this.stopGame());
        document.getElementById('btn-advance').addEventListener('click', () => this.advanceMission());
        document.getElementById('btn-play-again').addEventListener('click', () => this.showScreen('setup'));
        document.getElementById('btn-save-config').addEventListener('click', () => this.saveConfig());

        document.getElementById('input-test-mode').addEventListener('change', (e) => {
            document.getElementById('test-speaker-select').style.display = e.target.checked ? 'block' : 'none';
        });

        document.getElementById('btn-fetch-entities').addEventListener('click', () => this.fetchEntities());
        document.getElementById('btn-suggest').addEventListener('click', () => this.suggestChallenges());
        document.getElementById('btn-discover-speakers').addEventListener('click', () => this.discoverSpeakers());
        document.getElementById('btn-add-floor').addEventListener('click', () => this.addFloor());
        document.getElementById('btn-save-floors').addEventListener('click', () => this.saveFloors());
        document.getElementById('input-speaker-volume').addEventListener('input', (e) => {
            document.getElementById('volume-display').textContent = e.target.value + '%';
        });
        document.getElementById('input-speaker-volume').addEventListener('change', (e) => {
            fetch('/api/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ speaker_volume: parseInt(e.target.value, 10) / 100 }),
            });
        });

        // Hub speaker auto-save is set up in populateSpeakerDropdowns

        // Tab switching
        document.querySelectorAll('.tab').forEach(tab => {
            tab.addEventListener('click', () => {
                document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
                document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
                tab.classList.add('active');
                document.getElementById(tab.dataset.tab).classList.add('active');
            });
        });
    },

    selectTheme(slug) {
        this.selectedTheme = slug;
        document.querySelectorAll('.theme-card').forEach(card => {
            card.classList.toggle('selected', card.dataset.theme === slug);
        });
    },

    // --- Screens ---
    showScreen(name) {
        this.screen = name;
        document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
        document.getElementById(`screen-${name}`).classList.add('active');
    },

    showWaiting(message) {
        const area = document.getElementById('game-active-area');
        area.innerHTML = `
            <div class="waiting-message">
                <div class="spinner"></div>
                <div>${message}</div>
            </div>
        `;
        const targets = document.getElementById('targets-list');
        if (targets) targets.innerHTML = '';
    },

    // --- Game Actions ---
    async startGame() {
        const btn = document.getElementById('btn-launch');
        btn.disabled = true;
        btn.textContent = 'Starting...';

        const body = {
            theme: this.selectedTheme,
            rounds: parseInt(document.getElementById('input-rounds').value) || 5,
            difficulty: document.getElementById('input-difficulty').value,
            test_mode: document.getElementById('input-test-mode').checked,
            test_speaker: document.getElementById('input-test-speaker').value,
        };

        const selectedFloors = this.getSelectedFloors();
        if (selectedFloors) body.floors = selectedFloors;

        const haUrl = document.getElementById('input-ha-url').value.trim();
        if (haUrl) body.ha_url = haUrl;

        const hubSpeaker = document.getElementById('input-hub-speaker-select').value;
        if (hubSpeaker) body.hub_speaker = hubSpeaker;

        try {
            const resp = await fetch('/api/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            const data = await resp.json();
            if (data.error) {
                alert(data.error);
            }
        } catch (err) {
            alert('Failed to start game: ' + err.message);
        } finally {
            btn.disabled = false;
            btn.textContent = 'Launch Mission';
        }
    },

    async startGameATV() {
        const btn = document.getElementById('btn-launch-atv');
        btn.disabled = true;
        btn.textContent = 'Starting...';
        this.appleTVMode = true;

        const body = {
            theme: this.selectedTheme,
            rounds: parseInt(document.getElementById('input-rounds').value) || 5,
            difficulty: document.getElementById('input-difficulty').value,
            test_mode: document.getElementById('input-test-mode').checked,
            test_speaker: document.getElementById('input-test-speaker').value,
            appletv_mode: true,
        };

        const selectedFloors = this.getSelectedFloors();
        if (selectedFloors) body.floors = selectedFloors;

        const haUrl = document.getElementById('input-ha-url').value.trim();
        if (haUrl) body.ha_url = haUrl;

        const hubSpeaker = document.getElementById('input-hub-speaker-select').value;
        if (hubSpeaker) body.hub_speaker = hubSpeaker;

        try {
            const resp = await fetch('/api/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            const data = await resp.json();
            if (data.error) {
                alert(data.error);
            }
        } catch (err) {
            alert('Failed to start game: ' + err.message);
        } finally {
            btn.disabled = false;
            btn.textContent = 'Launch Mission (Apple TV)';
        }
    },

    async advanceMission() {
        const btn = document.getElementById('btn-advance');
        btn.disabled = true;
        try {
            await fetch('/api/advance', { method: 'POST' });
        } catch (err) {
            console.error('Advance failed:', err);
        }
        btn.disabled = false;
        btn.style.display = 'none';
    },

    async skipRound() {
        await fetch('/api/skip', { method: 'POST' });
    },

    async stopGame() {
        await fetch('/api/stop', { method: 'POST' });
    },

    // --- Render ---
    renderGameScreen() {
        const c = this.gameState.challenge;
        if (!c) return;

        const diffClass = `difficulty-${c.difficulty}`;

        // TV viewport content (matches tvOS layout)
        const area = document.getElementById('game-active-area');
        area.innerHTML = `
            <div class="tv-text-backdrop">
                <div class="round-label animate-in">Round ${this.gameState.currentRound} of ${this.gameState.totalRounds}</div>
                <div class="challenge-header">
                    <div class="challenge-name animate-in glow-pulse">${c.name}</div>
                    <div class="challenge-meta animate-in">
                        <span class="room-badge">${c.room}</span>
                        <span class="difficulty-badge ${diffClass}">${c.difficulty}</span>
                    </div>
                </div>
                <div class="timer-container animate-in">
                    <div class="timer-display" id="timer-display">0</div>
                    <div class="progress-bar-track">
                        <div class="progress-bar-fill" id="progress-fill" style="width: 0%"></div>
                    </div>
                </div>
            </div>
        `;

        // Targets outside TV viewport (HA device hints)
        const targetsList = document.getElementById('targets-list');
        targetsList.innerHTML = c.targets.map(t => `
            <div class="target-item">
                <div class="target-dot" data-entity="${t.entity_id}"></div>
                <span class="target-entity">${t.entity_id} → ${t.target_state}</span>
            </div>
        `).join('');

        this.updateScoreBar();
    },

    updateTimer() {
        const el = document.getElementById('timer-display');
        const fill = document.getElementById('progress-fill');
        if (!el || !fill) return;

        const elapsed = this.gameState.elapsed;
        el.textContent = Math.round(elapsed);

        // Color coding: green 0-15s, yellow 15-30s, red 30s+
        el.className = 'timer-display';
        fill.className = 'progress-bar-fill';
        if (elapsed > 30) {
            el.classList.add('danger');
            fill.classList.add('danger');
        } else if (elapsed > 15) {
            el.classList.add('warning');
            fill.classList.add('warning');
        } else {
            el.classList.add('safe');
            fill.classList.add('safe');
        }

        const pct = Math.min((elapsed / 45) * 100, 100);
        fill.style.width = pct + '%';

        const dangerVignette = document.getElementById('game-danger-vignette');
        if (dangerVignette) {
            dangerVignette.classList.toggle('pulse', elapsed > 30);
        }
    },

    updateTargets(targets) {
        targets.forEach(t => {
            const dot = document.querySelector(`.target-dot[data-entity="${t.entity_id}"]`);
            if (dot) {
                dot.classList.toggle('completed', t.completed);
            }
        });
    },

    updateScoreBar() {
        const gs = this.gameState;
        document.getElementById('score-completed').textContent = gs.completedCount;
        document.getElementById('score-total-time').textContent = Math.round(gs.totalTime) + 's';
        const avg = gs.completedCount > 0 ? Math.round(gs.totalTime / gs.completedCount) : '0';
        document.getElementById('score-avg-time').textContent = avg + 's';
    },

    // --- Cinematic Visuals ---
    applyThemeVisuals(slug) {
        const v = THEME_VISUALS[slug] || THEME_VISUALS.mission_control;
        const el = document.getElementById('screen-game');
        el.style.setProperty('--theme-primary', v.primary);
        el.style.setProperty('--theme-glow', v.glow);
        el.style.setProperty('--theme-gradient-start', v.gradientStart);
        el.style.setProperty('--theme-gradient-end', v.gradientEnd);
    },

    setBackgroundImage(url) {
        const el = document.getElementById('game-bg-image');
        if (!el) return;
        if (url) {
            el.classList.remove('loaded');
            el.style.backgroundImage = `url(${url})`;
            el.style.animation = 'none';
            el.offsetHeight; // force reflow to restart animation
            el.style.animation = '';
            const img = new Image();
            img.onload = () => el.classList.add('loaded');
            img.src = url;
        } else {
            el.classList.remove('loaded');
            el.style.backgroundImage = '';
        }
    },

    showRoundComplete(name, time) {
        const area = document.getElementById('game-active-area');
        area.innerHTML = `
            <div class="tv-text-backdrop">
                <div class="round-complete-screen">
                    <div class="round-complete-check">&#10003;</div>
                    <div class="round-complete-title">Mission Complete!</div>
                    <div class="round-complete-name">${name}</div>
                    <div class="round-complete-time">${Math.round(time)}s</div>
                </div>
            </div>
        `;
        const targets = document.getElementById('targets-list');
        if (targets) targets.innerHTML = '';
    },

    showFinale(completed, totalRounds) {
        const area = document.getElementById('game-active-area');
        area.innerHTML = `
            <div class="tv-text-backdrop">
                <div class="round-complete-screen">
                    <div class="finale-subtitle">ALL MISSIONS</div>
                    <div class="finale-title">Complete!</div>
                    <div class="finale-stats">${completed} of ${totalRounds} missions</div>
                </div>
            </div>
        `;
        const targets = document.getElementById('targets-list');
        if (targets) targets.innerHTML = '';
    },

    spawnConfetti() {
        const container = document.getElementById('confetti-container');
        if (!container) return;
        container.innerHTML = '';
        const v = THEME_VISUALS[this.currentThemeSlug] || THEME_VISUALS.mission_control;
        const colors = [
            `rgb(${v.primary})`,
            `rgb(${v.glow})`,
            'rgb(52, 211, 153)',
            'white',
        ];
        for (let i = 0; i < 30; i++) {
            const piece = document.createElement('div');
            piece.className = 'confetti-piece';
            piece.style.left = (20 + Math.random() * 60) + '%';
            piece.style.top = '10%';
            piece.style.backgroundColor = colors[Math.floor(Math.random() * colors.length)];
            piece.style.animationDelay = (Math.random() * 0.3) + 's';
            piece.style.animationDuration = (1.5 + Math.random() * 1) + 's';
            piece.style.width = (4 + Math.random() * 6) + 'px';
            piece.style.height = (4 + Math.random() * 6) + 'px';
            container.appendChild(piece);
        }
        setTimeout(() => { container.innerHTML = ''; }, 3000);
    },

    clearGameVisuals() {
        this.setBackgroundImage(null);
        this.currentThemeSlug = null;
        const dangerVignette = document.getElementById('game-danger-vignette');
        if (dangerVignette) dangerVignette.classList.remove('pulse');
        const confetti = document.getElementById('confetti-container');
        if (confetti) confetti.innerHTML = '';
    },

    updateConnectionStatus() {
        const dot = document.getElementById('connection-dot');
        if (dot) {
            dot.classList.toggle('connected', this.connected);
        }
    },

    // --- Challenge Setup ---
    async fetchEntities() {
        const btn = document.getElementById('btn-fetch-entities');
        const status = document.getElementById('entity-status');
        btn.disabled = true;
        btn.textContent = 'Scanning...';
        status.textContent = '';

        try {
            const [entResp, spkResp] = await Promise.all([
                fetch('/api/ha/entities'),
                fetch('/api/ha/speakers'),
            ]);

            if (!entResp.ok) {
                const err = await entResp.json();
                throw new Error(err.error || 'Failed to fetch entities');
            }

            this.fetchedEntities = await entResp.json();
            this.fetchedSpeakers = await spkResp.json();

            const areas = [...new Set(this.fetchedEntities.map(e => e.area))];
            status.textContent = `Found ${this.fetchedEntities.length} entities in ${areas.length} areas, ${this.fetchedSpeakers.length} speakers`;
            document.getElementById('btn-suggest').disabled = false;
        } catch (err) {
            status.textContent = 'Error: ' + err.message;
        } finally {
            btn.disabled = false;
            btn.textContent = 'Scan Entities';
        }
    },

    async suggestChallenges() {
        const btn = document.getElementById('btn-suggest');
        const status = document.getElementById('suggest-status');
        btn.disabled = true;
        btn.textContent = 'Generating (this takes ~30s)...';
        status.textContent = 'Sending entities to Claude AI...';

        try {
            const resp = await fetch('/api/challenges/suggest', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    entities: this.fetchedEntities,
                    user_prompt: document.getElementById('input-generation-prompt').value || undefined,
                }),
            });

            if (!resp.ok) {
                const err = await resp.json();
                throw new Error(err.error || 'Generation failed');
            }

            const data = await resp.json();
            status.textContent = `Generated ${data.suggestions.length} challenge suggestions`;
            this.renderSuggestions(data.suggestions);
        } catch (err) {
            status.textContent = 'Error: ' + err.message;
        } finally {
            btn.disabled = false;
            btn.textContent = 'Generate Suggestions';
        }
    },

    renderSuggestions(suggestions) {
        const area = document.getElementById('suggestions-area');
        if (!suggestions.length) {
            area.innerHTML = '<p class="setup-desc">No suggestions generated.</p>';
            return;
        }

        let html = `
            <div class="suggestions-header">
                <span>${suggestions.length} suggestions</span>
                <button class="btn-approve-all" onclick="App.approveAll()">Approve All</button>
            </div>
        `;

        for (const s of suggestions) {
            html += this.renderSuggestionCard(s);
        }

        area.innerHTML = html;
    },

    renderSuggestionCard(s) {
        const diffClass = `difficulty-${s.difficulty || 'easy'}`;
        const targets = (s.targets || []).map(t => `${t.entity_id} → ${t.target_state}`).join(', ');
        const targetPills = (s.targets || []).map(t =>
            `<span class="entity-pill">${t.entity_id} → ${t.target_state}</span>`
        ).join('');

        const allowedSpk = this.allowedSpeakers || [];
        const speakerName = (id) => {
            const sp = allowedSpk.find(sp => sp.entity_id === id);
            return sp ? sp.friendly_name : id;
        };
        const speakerOpts = (selected) => allowedSpk.map(sp =>
            `<option value="${sp.entity_id}" ${sp.entity_id === selected ? 'selected' : ''}>${sp.friendly_name} (${sp.area})</option>`
        ).join('') + (selected && !allowedSpk.find(sp => sp.entity_id === selected)
            ? `<option value="${selected}" selected>${selected}</option>` : '');

        const floors = this.floors || [];
        const floorOpts = `<option value="" ${!s.floor ? 'selected' : ''}>— None —</option>` +
            floors.map(f => `<option value="${f.name}" ${f.name === s.floor ? 'selected' : ''}>${f.name}</option>`).join('');

        const successSpkLabel = speakerName(s.success_speaker);
        const floorBadge = s.floor ? `<span class="floor-badge">${s.floor}</span>` : '';

        return `
            <div class="challenge-row" id="suggestion-${s.id}">
                <div class="approved-challenge-item suggestion-row" onclick="App.toggleSuggestionDetail('${s.id}')">
                    <div class="approved-challenge-info">
                        <span class="difficulty-badge ${diffClass}" style="font-size:0.65rem">${s.difficulty || 'easy'}</span>
                        <span class="approved-challenge-name">${s.name || 'Unnamed'}</span>
                        <span class="approved-challenge-room">${s.room || ''}</span>
                        ${floorBadge}
                        ${s.multi_target ? '<span class="difficulty-badge difficulty-hard" style="font-size:0.6rem">Multi</span>' : ''}
                        <span class="approved-challenge-speaker">${successSpkLabel}</span>
                    </div>
                    <div class="suggestion-actions-inline" onclick="event.stopPropagation()">
                        <button class="btn-approve" onclick="App.approveChallenge('${s.id}')">Approve</button>
                        <button class="btn-ignore" onclick="App.ignoreSuggestion('${s.id}')">Ignore</button>
                        <button class="btn-deny" onclick="App.denyChallenge('${s.id}')">Reject Device</button>
                    </div>
                </div>
                <div class="challenge-detail" id="sug-detail-${s.id}" style="display:none">
                    <div class="detail-row">
                        <span class="detail-label">Announcement</span>
                        <span class="detail-value detail-text" id="sug-field-announcement-${s.id}">${s.announcement || ''}</span>
                        <button class="btn-regen" id="regen-pending-announcement-${s.id}" onclick="event.stopPropagation(); App.regenerateField('${s.id}', 'announcement', 'pending')" title="Regenerate">&#x21bb;</button>
                    </div>
                    ${(s.funny_announcements && s.funny_announcements.length) ? `
                    ${s.funny_announcements.map((f, i) => `
                    <div class="detail-row">
                        <span class="detail-label">Funny ${i + 1}</span>
                        <span class="detail-value detail-text" id="sug-field-funny-${i}-${s.id}" style="color:var(--text-muted);font-style:italic">${f}</span>
                    </div>`).join('')}
                    <div class="detail-row">
                        <span class="detail-label"></span>
                        <span class="detail-value"></span>
                        <button class="btn-regen" id="regen-pending-funny_announcements-${s.id}" onclick="event.stopPropagation(); App.regenerateField('${s.id}', 'funny_announcements', 'pending')" title="Regenerate funny variants">&#x21bb; Funny</button>
                    </div>` : ''}
                    <div class="detail-row">
                        <span class="detail-label">Hint</span>
                        <span class="detail-value detail-text" id="sug-field-hint-${s.id}">${s.hint || ''}</span>
                        <button class="btn-regen" id="regen-pending-hint-${s.id}" onclick="event.stopPropagation(); App.regenerateField('${s.id}', 'hint', 'pending')" title="Regenerate">&#x21bb;</button>
                    </div>
                    <div class="detail-row">
                        <span class="detail-label">Targets</span>
                        <span class="detail-value">${targetPills}</span>
                    </div>
                    <div class="detail-row">
                        <span class="detail-label">Difficulty</span>
                        <select class="detail-select" id="sug-difficulty-${s.id}">
                            <option value="easy" ${s.difficulty === 'easy' ? 'selected' : ''}>Easy</option>
                            <option value="medium" ${s.difficulty === 'medium' ? 'selected' : ''}>Medium</option>
                            <option value="hard" ${s.difficulty === 'hard' ? 'selected' : ''}>Hard</option>
                        </select>
                    </div>
                    <div class="detail-row">
                        <span class="detail-label">Floor</span>
                        <select class="detail-select" id="sug-floor-${s.id}">${floorOpts}</select>
                    </div>
                    <div class="detail-row">
                        <span class="detail-label">Success Speaker</span>
                        <select class="detail-select" id="sug-success-spk-${s.id}">${speakerOpts(s.success_speaker)}</select>
                    </div>
                    <div class="detail-actions" id="actions-${s.id}">
                        <button class="btn-rethink" onclick="App.showRethink('${s.id}')">Re-think</button>
                        <button class="btn-approve" onclick="App.approveChallenge('${s.id}')">Approve</button>
                        <button class="btn-ignore" onclick="App.ignoreSuggestion('${s.id}')">Ignore</button>
                        <button class="btn-deny" onclick="App.denyChallenge('${s.id}')">Reject Device</button>
                    </div>
                    <div class="rethink-panel" id="rethink-${s.id}" style="display:none">
                        <textarea class="rethink-input" id="rethink-input-${s.id}" placeholder="Guide the AI... e.g. 'Make it harder' or 'Use a different entity' or 'Make it funnier'"></textarea>
                        <div class="rethink-actions">
                            <button class="btn-approve" onclick="App.submitRethink('${s.id}')">Send</button>
                            <button class="btn-deny" onclick="App.hideRethink('${s.id}')">Cancel</button>
                        </div>
                    </div>
                </div>
            </div>
        `;
    },

    toggleSuggestionDetail(id) {
        const detail = document.getElementById(`sug-detail-${id}`);
        if (detail) {
            detail.style.display = detail.style.display === 'none' ? 'block' : 'none';
        }
    },

    showRethink(id) {
        document.getElementById(`rethink-${id}`).style.display = 'block';
        document.getElementById(`rethink-input-${id}`).focus();
    },

    hideRethink(id) {
        document.getElementById(`rethink-${id}`).style.display = 'none';
    },

    async submitRethink(id) {
        const input = document.getElementById(`rethink-input-${id}`);
        const feedback = input.value.trim();
        if (!feedback) return;

        const card = document.getElementById(`suggestion-${id}`);
        const actions = document.getElementById(`actions-${id}`);
        const rethinkPanel = document.getElementById(`rethink-${id}`);

        // Show loading state
        rethinkPanel.style.display = 'none';
        actions.innerHTML = '<span class="rethink-loading">Re-thinking...</span>';

        try {
            const resp = await fetch('/api/challenges/rethink', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ challenge_id: id, feedback }),
            });

            if (!resp.ok) {
                const err = await resp.json();
                throw new Error(err.error || 'Rethink failed');
            }

            const data = await resp.json();
            const revised = data.challenge;

            // Replace the card with the revised version, keeping it expanded
            card.outerHTML = this.renderSuggestionCard(revised);
            const detail = document.getElementById(`sug-detail-${id}`);
            if (detail) detail.style.display = 'block';
        } catch (err) {
            actions.innerHTML = `
                <span class="rethink-error">Error: ${err.message}</span>
                <button class="btn-approve" onclick="App.approveChallenge('${id}')">Approve</button>
                <button class="btn-rethink" onclick="App.showRethink('${id}')">Re-think</button>
                <button class="btn-ignore" onclick="App.ignoreSuggestion('${id}')">Ignore</button>
                <button class="btn-deny" onclick="App.denyChallenge('${id}')">Reject Device</button>
            `;
        }
    },

    async approveChallenge(id) {
        // Collect any overrides from the expanded detail panel
        const overrides = {};
        const diffEl = document.getElementById(`sug-difficulty-${id}`);
        if (diffEl) overrides.difficulty = diffEl.value;
        const floorEl = document.getElementById(`sug-floor-${id}`);
        if (floorEl) overrides.floor = floorEl.value;
        const successEl = document.getElementById(`sug-success-spk-${id}`);
        if (successEl) overrides.success_speaker = successEl.value;

        try {
            const resp = await fetch('/api/challenges/approve', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ challenge_id: id, approved: true, overrides }),
            });
            if (resp.ok) {
                const card = document.getElementById(`suggestion-${id}`);
                if (card) card.classList.add('approved');
                this.loadChallenges();
            }
        } catch (err) {
            console.error('Approve failed:', err);
        }
    },

    ignoreSuggestion(id) {
        const card = document.getElementById(`suggestion-${id}`);
        if (card) card.classList.add('ignored');
    },

    async denyChallenge(id) {
        try {
            const resp = await fetch('/api/challenges/approve', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ challenge_id: id, approved: false }),
            });
            if (resp.ok) {
                const card = document.getElementById(`suggestion-${id}`);
                if (card) card.classList.add('denied');
                this.loadBlacklist();
            }
        } catch (err) {
            console.error('Deny failed:', err);
        }
    },

    async approveAll() {
        try {
            const resp = await fetch('/api/challenges/approve-all', { method: 'POST' });
            if (resp.ok) {
                const data = await resp.json();
                document.querySelectorAll('.suggestion-card').forEach(c => c.classList.add('approved'));
                document.getElementById('suggest-status').textContent = `Approved ${data.count} challenges`;
                this.loadChallenges();
            }
        } catch (err) {
            console.error('Approve all failed:', err);
        }
    },

    async deleteChallenge(id) {
        try {
            await fetch(`/api/challenges/${id}`, { method: 'DELETE' });
            this.loadChallenges();
        } catch (err) {
            console.error('Delete failed:', err);
        }
    },

    async loadChallenges() {
        try {
            const resp = await fetch('/api/challenges');
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const data = await resp.json();
            const challenges = data.challenges || [];
            const count = challenges.length;

            // Update summary on main screen (always visible)
            const summary = document.getElementById('challenge-db-summary');
            if (summary) {
                summary.textContent = count > 0
                    ? `${count} challenges ready`
                    : 'No challenges yet — generate some in the Challenges tab';
            }

            // Update max rounds input
            const roundsInput = document.getElementById('input-rounds');
            if (roundsInput && count > 0) {
                roundsInput.max = count;
            }

            // Render challenge list
            const list = document.getElementById('approved-challenges-list');
            if (!list) return;

            if (count === 0) {
                list.innerHTML = '<p class="setup-desc">No challenges yet. Scan entities and generate some below.</p>';
                return;
            }

            // Build speaker options from allowed speakers for dropdowns
            const configResp2 = await fetch('/api/config');
            const config2 = await configResp2.json();
            const allowedSpk = config2.allowed_speakers || [];
            const speakerName = (id) => {
                const s = allowedSpk.find(s => s.entity_id === id);
                return s ? s.friendly_name : id;
            };
            const speakerOpts = (selected) => allowedSpk.map(s =>
                `<option value="${s.entity_id}" ${s.entity_id === selected ? 'selected' : ''}>${s.friendly_name} (${s.area})</option>`
            ).join('') + (selected && !allowedSpk.find(s => s.entity_id === selected)
                ? `<option value="${selected}" selected>${selected}</option>` : '');

            // Floor options for dropdown
            const floors = config2.floors || [];
            const floorOpts = (selected) => `<option value="" ${!selected ? 'selected' : ''}>— None —</option>` +
                floors.map(f => `<option value="${f.name}" ${f.name === selected ? 'selected' : ''}>${f.name}</option>`).join('');

            let html = `<div class="challenges-summary">${count} challenges</div>`;

            html += challenges.map(c => {
                const targets = (c.targets || []).map(t => `${t.entity_id} → ${t.target_state}`).join(', ');
                const successSpkLabel = speakerName(c.success_speaker);
                const floorBadge = c.floor ? `<span class="floor-badge">${c.floor}</span>` : '';
                return `
                    <div class="challenge-row" id="challenge-row-${c.id}">
                        <div class="approved-challenge-item" onclick="App.toggleChallengeDetail('${c.id}')">
                            <div class="approved-challenge-info">
                                <span class="difficulty-badge difficulty-${c.difficulty || 'easy'}" style="font-size:0.65rem">${c.difficulty || 'easy'}</span>
                                <span class="approved-challenge-name">${c.name || 'Unnamed'}</span>
                                <span class="approved-challenge-room">${c.room || ''}</span>
                                ${floorBadge}
                                <span class="approved-challenge-speaker">${successSpkLabel}</span>
                            </div>
                            <button class="btn-delete-challenge" onclick="event.stopPropagation(); App.deleteChallenge('${c.id}')">Delete</button>
                        </div>
                        <div class="challenge-detail" id="detail-${c.id}" style="display:none">
                            <div class="detail-row">
                                <span class="detail-label">Targets</span>
                                <span class="detail-value"><span class="entity-pill">${targets}</span></span>
                            </div>
                            <div class="detail-row">
                                <span class="detail-label">Announcement</span>
                                <span class="detail-value detail-text" id="approved-field-announcement-${c.id}">${c.announcement || ''}</span>
                                <button class="btn-regen" id="regen-approved-announcement-${c.id}" onclick="event.stopPropagation(); App.regenerateField('${c.id}', 'announcement', 'approved')" title="Regenerate">&#x21bb;</button>
                            </div>
                            ${(c.funny_announcements && c.funny_announcements.length) ? `
                            ${c.funny_announcements.map((f, i) => `
                            <div class="detail-row">
                                <span class="detail-label">Funny ${i + 1}</span>
                                <span class="detail-value detail-text" id="approved-field-funny-${i}-${c.id}" style="color:var(--text-muted);font-style:italic">${f}</span>
                            </div>`).join('')}
                            <div class="detail-row">
                                <span class="detail-label"></span>
                                <span class="detail-value"></span>
                                <button class="btn-regen" id="regen-approved-funny_announcements-${c.id}" onclick="event.stopPropagation(); App.regenerateField('${c.id}', 'funny_announcements', 'approved')" title="Regenerate funny variants">&#x21bb; Funny</button>
                            </div>` : ''}
                            <div class="detail-row">
                                <span class="detail-label">Hint</span>
                                <span class="detail-value detail-text" id="approved-field-hint-${c.id}">${c.hint || ''}</span>
                                <button class="btn-regen" id="regen-approved-hint-${c.id}" onclick="event.stopPropagation(); App.regenerateField('${c.id}', 'hint', 'approved')" title="Regenerate">&#x21bb;</button>
                            </div>
                            <div class="detail-row">
                                <span class="detail-label">Difficulty</span>
                                <select class="detail-select" id="difficulty-${c.id}">
                                    <option value="easy" ${c.difficulty === 'easy' ? 'selected' : ''}>Easy</option>
                                    <option value="medium" ${c.difficulty === 'medium' ? 'selected' : ''}>Medium</option>
                                    <option value="hard" ${c.difficulty === 'hard' ? 'selected' : ''}>Hard</option>
                                </select>
                            </div>
                            <div class="detail-row">
                                <span class="detail-label">Floor</span>
                                <select class="detail-select" id="floor-${c.id}">${floorOpts(c.floor)}</select>
                            </div>
                            <div class="detail-row">
                                <span class="detail-label">Success Speaker</span>
                                <select class="detail-select" id="success-spk-${c.id}">${speakerOpts(c.success_speaker)}</select>
                            </div>
                            <div class="detail-actions">
                                <button class="btn-approve" onclick="App.saveChallengeDetail('${c.id}')">Save</button>
                            </div>
                        </div>
                    </div>
                `;
            }).join('');


            list.innerHTML = html;
        } catch (err) {
            console.error('Failed to load challenges:', err);
            const list = document.getElementById('approved-challenges-list');
            if (list) list.innerHTML = `<p class="setup-desc" style="color:var(--danger)">Error loading challenges: ${err.message}</p>`;
        }
    },

    toggleChallengeDetail(id) {
        const detail = document.getElementById(`detail-${id}`);
        if (detail) {
            detail.style.display = detail.style.display === 'none' ? 'block' : 'none';
        }
    },

    async saveChallengeDetail(id) {
        const successSpk = document.getElementById(`success-spk-${id}`).value;
        const difficulty = document.getElementById(`difficulty-${id}`).value;
        const floor = document.getElementById(`floor-${id}`).value;

        try {
            const resp = await fetch(`/api/challenges/${id}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    success_speaker: successSpk,
                    difficulty,
                    floor,
                }),
            });
            if (resp.ok) {
                const btn = document.querySelector(`#detail-${id} .btn-approve`);
                if (btn) { btn.textContent = 'Saved!'; setTimeout(() => btn.textContent = 'Save', 1500); }
                this.loadChallenges();
            }
        } catch (err) {
            console.error('Save failed:', err);
        }
    },

    async regenerateField(challengeId, field, source) {
        const btn = document.getElementById(`regen-${source}-${field}-${challengeId}`);
        if (btn) { btn.classList.add('loading'); btn.disabled = true; }
        try {
            const resp = await fetch('/api/challenges/regenerate-field', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ challenge_id: challengeId, field, source }),
            });
            if (resp.ok) {
                const data = await resp.json();
                // Determine the element prefix based on source
                const prefix = source === 'approved' ? 'approved' : 'sug';
                if (field === 'funny_announcements' && Array.isArray(data.value)) {
                    // Update funny text spans in place
                    data.value.forEach((text, i) => {
                        const el = document.getElementById(`${prefix}-field-funny-${i}-${challengeId}`);
                        if (el) el.textContent = text;
                    });
                } else {
                    const el = document.getElementById(`${prefix}-field-${field}-${challengeId}`);
                    if (el) el.textContent = data.value;
                }
            }
        } catch (err) {
            console.error('Regenerate failed:', err);
        } finally {
            if (btn) { btn.classList.remove('loading'); btn.disabled = false; }
        }
    },

    // --- Blacklist ---
    async loadBlacklist() {
        try {
            const resp = await fetch('/api/blacklist');
            const data = await resp.json();
            const list = document.getElementById('blacklist-list');
            if (!list) return;

            if (!data.blacklist.length) {
                list.innerHTML = '<p class="setup-desc">No blacklisted entities.</p>';
                return;
            }

            list.innerHTML = `
                <div class="blacklist-header">
                    <span>${data.blacklist.length} blacklisted</span>
                    <button class="btn-deny" onclick="App.clearBlacklist()" style="font-size:0.75rem;padding:4px 10px">Clear All</button>
                </div>
                ${data.blacklist.map(eid => `
                    <div class="blacklist-item">
                        <span class="entity-pill">${eid}</span>
                        <button class="btn-delete-challenge" onclick="App.removeFromBlacklist('${eid}')">Remove</button>
                    </div>
                `).join('')}
            `;
        } catch (err) {
            console.error('Failed to load blacklist:', err);
        }
    },

    async removeFromBlacklist(entityId) {
        try {
            await fetch('/api/blacklist/remove', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ entity_ids: [entityId] }),
            });
            this.loadBlacklist();
        } catch (err) {
            console.error('Remove from blacklist failed:', err);
        }
    },

    async clearBlacklist() {
        try {
            await fetch('/api/blacklist/clear', { method: 'POST' });
            this.loadBlacklist();
        } catch (err) {
            console.error('Clear blacklist failed:', err);
        }
    },

    // --- Intro Music ---
    introAudio: null,

    async loadIntroMusic() {
        try {
            const resp = await fetch('/api/intro-music');
            const data = await resp.json();
            const list = document.getElementById('intro-music-list');
            if (!list) return;

            list.innerHTML = data.music.map(m => `
                <div class="intro-music-item">
                    <div class="intro-music-info">
                        <span class="intro-music-name">${m.theme_name}</span>
                        <span class="intro-music-status ${m.exists ? 'cached' : 'missing'}">${m.exists ? (m.size / 1024).toFixed(0) + ' KB' : 'Not generated'}</span>
                    </div>
                    <div class="intro-music-actions">
                        ${m.exists ? `<button class="btn-approve" onclick="App.playIntroMusic('${m.audio_url}', this)">Play</button>` : ''}
                        <button class="btn-rethink" onclick="App.generateIntroMusic('${m.theme}')">${m.exists ? 'Regenerate' : 'Generate'}</button>
                        ${m.exists ? `<button class="btn-deny" onclick="App.deleteIntroMusic('${m.theme}')">Delete</button>` : ''}
                    </div>
                </div>
            `).join('');
        } catch (err) {
            console.error('Failed to load intro music:', err);
        }
    },

    playIntroMusic(url, btn) {
        // Stop current playback if any
        const wasPlaying = !!this.introAudio;
        if (this.introAudio) {
            this.introAudio.pause();
            this.introAudio = null;
            // Reset only intro music Play/Stop buttons (not scene image Preview buttons)
            document.querySelectorAll('#intro-music-list .btn-approve').forEach(b => b.textContent = 'Play');
        }
        // If this button was already playing, just stop
        if (wasPlaying && btn && btn.textContent === 'Play') {
            return;
        }
        this.introAudio = new Audio(url);
        this.introAudio.play();
        if (btn) btn.textContent = 'Stop';
        this.introAudio.onended = () => {
            if (btn) btn.textContent = 'Play';
            this.introAudio = null;
        };
    },

    async generateIntroMusic(slug) {
        const list = document.getElementById('intro-music-list');
        // Find and disable the button
        const btns = list.querySelectorAll('.btn-rethink');
        btns.forEach(b => { if (b.onclick.toString().includes(slug)) { b.disabled = true; b.textContent = 'Generating...'; } });

        try {
            const resp = await fetch(`/api/intro-music/${slug}/generate`, { method: 'POST' });
            if (!resp.ok) {
                const err = await resp.json();
                throw new Error(err.error || 'Failed');
            }
            this.loadIntroMusic();
        } catch (err) {
            alert('Generation failed: ' + err.message);
            this.loadIntroMusic();
        }
    },

    async deleteIntroMusic(slug) {
        try {
            await fetch(`/api/intro-music/${slug}`, { method: 'DELETE' });
            if (this.introAudio) { this.introAudio.pause(); this.introAudio = null; }
            this.loadIntroMusic();
        } catch (err) {
            console.error('Delete intro music failed:', err);
        }
    },

    // --- Scene Images ---

    async loadSceneImages() {
        try {
            const resp = await fetch('/api/scene-images');
            const data = await resp.json();
            const list = document.getElementById('scene-images-list');
            if (!list) return;

            list.innerHTML = data.images.map(img => `
                <div class="intro-music-item">
                    <div class="intro-music-info" style="flex:1">
                        <span class="intro-music-name">${img.theme_name} — ${img.label}</span>
                        <span class="intro-music-status ${img.exists ? 'cached' : 'missing'}">${img.exists ? (img.size / 1024).toFixed(0) + ' KB' : 'Not generated'}</span>
                    </div>
                    <div class="intro-music-actions">
                        ${img.exists ? `<button class="btn-approve" onclick="App.previewSceneImage('${img.image_url}', this)">Preview</button>` : ''}
                        <button class="btn-rethink" onclick="App.generateSceneImage('${img.theme}', '${img.type}')">${img.exists ? 'Regenerate' : 'Generate'}</button>
                        ${img.exists ? `<button class="btn-deny" onclick="App.deleteSceneImage('${img.theme}', '${img.type}')">Delete</button>` : ''}
                    </div>
                </div>
            `).join('');
        } catch (err) {
            console.error('Failed to load scene images:', err);
        }
    },

    previewSceneImage(url, btn) {
        // Toggle preview image below the button row
        const item = btn.closest('.intro-music-item');
        const existing = item.querySelector('.scene-image-preview');
        if (existing) {
            existing.remove();
            return;
        }
        const preview = document.createElement('div');
        preview.className = 'scene-image-preview';
        preview.style.cssText = 'margin-top:8px;width:100%';
        preview.innerHTML = `<img src="${url}" style="max-width:400px;border-radius:8px;border:1px solid rgba(255,255,255,0.1)">`;
        item.appendChild(preview);
    },

    async generateSceneImage(themeSlug, imageType) {
        const list = document.getElementById('scene-images-list');
        const btns = list.querySelectorAll('.btn-rethink');
        btns.forEach(b => {
            if (b.onclick.toString().includes(themeSlug) && b.onclick.toString().includes(imageType)) {
                b.disabled = true; b.textContent = 'Generating...';
            }
        });

        try {
            const resp = await fetch(`/api/scene-images/generate?theme_slug=${themeSlug}&image_type=${imageType}`, { method: 'POST' });
            if (!resp.ok) {
                const err = await resp.json();
                throw new Error(err.error || 'Failed');
            }
            this.loadSceneImages();
        } catch (err) {
            alert('Image generation failed: ' + err.message);
            this.loadSceneImages();
        }
    },

    async generateAllSceneImages() {
        const btn = event.target;
        btn.disabled = true;
        btn.textContent = 'Generating...';

        try {
            const resp = await fetch('/api/scene-images/generate-all', { method: 'POST' });
            const data = await resp.json();
            if (!resp.ok) throw new Error(data.error || 'Failed');
            btn.textContent = `Done! ${data.generated} new, ${data.cached} cached`;
            setTimeout(() => { btn.textContent = 'Generate All Missing'; btn.disabled = false; }, 3000);
            this.loadSceneImages();
        } catch (err) {
            alert('Generation failed: ' + err.message);
            btn.textContent = 'Generate All Missing';
            btn.disabled = false;
        }
    },

    async deleteSceneImage(themeSlug, imageType) {
        try {
            await fetch(`/api/scene-images?theme_slug=${themeSlug}&image_type=${imageType}`, { method: 'DELETE' });
            this.loadSceneImages();
        } catch (err) {
            console.error('Delete scene image failed:', err);
        }
    },

    async deleteAllSceneImages() {
        try {
            await fetch('/api/scene-images/all', { method: 'DELETE' });
            this.loadSceneImages();
        } catch (err) {
            console.error('Delete all scene images failed:', err);
        }
    },

    // --- Cache Management ---

    async clearTtsCache() {
        const status = document.getElementById('cache-clear-status');
        try {
            const resp = await fetch('/api/cache/tts', { method: 'DELETE' });
            const data = await resp.json();
            if (data.error) {
                if (status) status.textContent = data.error;
                return;
            }
            if (status) status.textContent = `Cleared ${data.deleted} TTS files`;
            this.loadIntroMusic();
        } catch (err) {
            console.error('Clear TTS cache failed:', err);
            if (status) status.textContent = 'Failed to clear cache';
        }
    },

    async clearAllCache() {
        if (!confirm('This will delete all cached audio (including intro music) and scene images. Continue?')) return;
        const status = document.getElementById('cache-clear-status');
        try {
            const resp = await fetch('/api/cache/all', { method: 'DELETE' });
            const data = await resp.json();
            if (data.error) {
                if (status) status.textContent = data.error;
                return;
            }
            if (status) status.textContent = `Cleared ${data.deleted} files`;
            this.loadIntroMusic();
            this.loadSceneImages();
        } catch (err) {
            console.error('Clear all cache failed:', err);
            if (status) status.textContent = 'Failed to clear cache';
        }
    },

    // --- Theme Phrases ---

    async loadThemePhrases() {
        try {
            const resp = await fetch('/api/themes/phrases');
            const data = await resp.json();
            const container = document.getElementById('theme-phrases-list');
            if (!container) return;

            let html = '';
            for (const [slug, theme] of Object.entries(data.themes)) {
                html += `<div class="theme-phrases-group">
                    <div class="theme-phrases-header">${theme.name}</div>`;

                const phraseTypes = [
                    ['announcement_prefixes', 'Mission Announcement Prefixes', '(prepended to each mission announcement)'],
                    ['success_prefixes', 'Success Prefixes', '(prepended to success messages)'],
                    ['hint_prefixes', 'Hint Prefixes', '(prepended to hint messages)'],
                    ['timeout_phrases', 'Timeout / Failure Phrases', '(spoken when time runs out)'],
                    ['intro_texts', 'Intro Phrases', ''],
                    ['outro_texts', 'Outro Phrases', '({total_time} and {rounds} are placeholders)'],
                ];
                for (const [phraseType, label, noteText] of phraseTypes) {
                    const phrases = theme.phrases[phraseType];
                    let notes = noteText ? ` <span style="color:#888;font-size:11px">${noteText}</span>` : '';
                    html += `<div class="theme-phrases-section">
                        <div class="theme-phrases-label">${label}${notes}</div>`;

                    phrases.forEach((text, i) => {
                        html += `<div class="intro-music-item" style="align-items:flex-start">
                            <div class="intro-music-info" style="flex:1">
                                <span class="theme-phrase-text" id="phrase-${slug}-${phraseType}-${i}">${this.escapeHtml(text)}</span>
                            </div>
                            <div class="intro-music-actions" style="flex-shrink:0">
                                <button class="btn-approve" onclick="App.editPhrase('${slug}', '${phraseType}', ${i})">Edit</button>
                                <button class="btn-rethink" onclick="App.regeneratePhrase('${slug}', '${phraseType}', ${i}, this)">Regen</button>
                                <button class="btn-deny" onclick="App.deletePhrase('${slug}', '${phraseType}', ${i})">Del</button>
                            </div>
                        </div>`;
                    });

                    html += `<div style="margin-top:6px;display:flex;gap:8px">
                        <button class="btn btn-secondary btn-small" onclick="App.addPhrase('${slug}', '${phraseType}')">+ Add Phrase</button>
                        <button class="btn btn-secondary btn-small" onclick="App.regeneratePhrase('${slug}', '${phraseType}', -1, this)">+ Generate New</button>
                        <button class="btn btn-secondary btn-small" style="margin-left:auto" onclick="App.resetPhrases('${slug}', '${phraseType}')">Reset to Default</button>
                    </div>`;
                    html += `</div>`;
                }


                html += `</div>`;
            }
            container.innerHTML = html;
        } catch (err) {
            console.error('Failed to load theme phrases:', err);
        }
    },

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    },

    async editPhrase(slug, phraseType, index) {
        const el = document.getElementById(`phrase-${slug}-${phraseType}-${index}`);
        if (!el) return;
        const current = el.textContent;
        const newText = prompt('Edit phrase:', current);
        if (newText === null || newText === current) return;

        try {
            const resp = await fetch('/api/themes/phrases/update', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ theme_slug: slug, phrase_type: phraseType, index, text: newText }),
            });
            if (!resp.ok) {
                const err = await resp.json();
                throw new Error(err.error || 'Failed');
            }
            this.loadThemePhrases();
        } catch (err) {
            alert('Update failed: ' + err.message);
        }
    },

    async regeneratePhrase(slug, phraseType, index, btn) {
        if (btn) { btn.disabled = true; btn.textContent = 'Generating...'; }

        // If index is -1, we're generating a new phrase to add
        const isNew = index === -1;
        if (isNew) index = 0;  // regenerate slot 0 pattern but we'll add instead

        try {
            if (isNew) {
                // First add a placeholder, then regenerate it
                const addResp = await fetch('/api/themes/phrases/add', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ theme_slug: slug, phrase_type: phraseType, text: '(generating...)' }),
                });
                if (!addResp.ok) throw new Error('Failed to add');
                const addData = await addResp.json();
                index = addData.index;
            }

            const resp = await fetch('/api/themes/phrases/regenerate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ theme_slug: slug, phrase_type: phraseType, index }),
            });
            if (!resp.ok) {
                const err = await resp.json();
                throw new Error(err.error || 'Failed');
            }
            this.loadThemePhrases();
        } catch (err) {
            alert('Regeneration failed: ' + err.message);
            this.loadThemePhrases();
        }
    },

    async addPhrase(slug, phraseType) {
        const text = prompt('Enter new phrase:' + (phraseType === 'outro_texts' ? '\n(Use {total_time} and {rounds} as placeholders)' : ''));
        if (!text) return;

        try {
            const resp = await fetch('/api/themes/phrases/add', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ theme_slug: slug, phrase_type: phraseType, text }),
            });
            if (!resp.ok) {
                const err = await resp.json();
                throw new Error(err.error || 'Failed');
            }
            this.loadThemePhrases();
        } catch (err) {
            alert('Add failed: ' + err.message);
        }
    },

    async deletePhrase(slug, phraseType, index) {
        if (!confirm('Delete this phrase?')) return;

        try {
            const resp = await fetch('/api/themes/phrases/delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ theme_slug: slug, phrase_type: phraseType, index }),
            });
            if (!resp.ok) {
                const err = await resp.json();
                throw new Error(err.error || 'Failed');
            }
            this.loadThemePhrases();
        } catch (err) {
            alert('Delete failed: ' + err.message);
        }
    },

    async resetPhrases(slug, phraseType) {
        if (!confirm(`Reset ${phraseType.replace('_', ' ')} for this theme to defaults?`)) return;

        try {
            await fetch(`/api/themes/phrases/reset?theme_slug=${slug}&phrase_type=${phraseType}`, { method: 'POST' });
            this.loadThemePhrases();
        } catch (err) {
            console.error('Reset failed:', err);
        }
    },

    // --- Split Button Dropdowns ---
    toggleDropdown(menuId) {
        const menu = document.getElementById(menuId);
        const wasOpen = menu.style.display !== 'none';
        this.closeDropdowns();
        if (!wasOpen) menu.style.display = 'block';
    },

    closeDropdowns() {
        document.getElementById('launch-dropdown-menu').style.display = 'none';
        document.getElementById('launch-atv-dropdown-menu').style.display = 'none';
    },

    // --- Review & Launch ---
    reviewChallenges: [],
    reviewATVMode: false,

    async reviewAndLaunch(atvMode) {
        this.reviewATVMode = atvMode;
        const rounds = parseInt(document.getElementById('input-rounds').value) || 5;
        const difficulty = document.getElementById('input-difficulty').value;
        const selectedFloors = this.getSelectedFloors();

        const body = { rounds, difficulty };
        if (selectedFloors) body.floors = selectedFloors;

        try {
            const resp = await fetch('/api/challenges/preview', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            if (!resp.ok) {
                const err = await resp.json();
                alert(err.error || 'Preview failed');
                return;
            }
            const data = await resp.json();
            this.reviewChallenges = data.challenges;
            this.renderReviewPanel();
        } catch (err) {
            alert('Failed to preview: ' + err.message);
        }
    },

    renderReviewPanel() {
        const panel = document.getElementById('review-panel');
        const list = document.getElementById('review-challenge-list');
        const countEl = document.getElementById('review-count');
        panel.style.display = 'block';

        const active = this.reviewChallenges.filter(c => !c._removed);
        countEl.textContent = `${active.length} challenge${active.length !== 1 ? 's' : ''} selected`;

        const allowedSpk = this.allowedSpeakers || [];
        const speakerName = (id) => {
            const s = allowedSpk.find(s => s.entity_id === id);
            return s ? `${s.friendly_name} (${s.area})` : id;
        };

        list.innerHTML = this.reviewChallenges.map((c, i) => {
            const removed = c._removed ? ' removed' : '';
            const floorBadge = c.floor ? `<span class="floor-badge">${c.floor}</span>` : '';
            return `
                <div class="review-challenge-item${removed}" id="review-item-${i}">
                    <div class="review-challenge-info">
                        <span class="difficulty-badge difficulty-${c.difficulty}" style="font-size:0.65rem">${c.difficulty}</span>
                        <span class="review-challenge-name">${c.name}</span>
                        <span class="approved-challenge-room">${c.room || ''}</span>
                        ${floorBadge}
                        <span class="approved-challenge-speaker">${speakerName(c.success_speaker)}</span>
                    </div>
                    <div class="review-actions">
                        ${c._removed ? '' : `
                            <button class="btn-shuffle" onclick="App.shuffleReviewChallenge(${i})" title="Swap for a different challenge">Shuffle</button>
                            <button class="btn-remove" onclick="App.removeReviewChallenge(${i})" title="Remove this challenge">Remove</button>
                        `}
                    </div>
                </div>
            `;
        }).join('');
    },

    removeReviewChallenge(index) {
        this.reviewChallenges[index]._removed = true;
        this.renderReviewPanel();
    },

    async shuffleReviewChallenge(index) {
        const difficulty = document.getElementById('input-difficulty').value;
        const selectedFloors = this.getSelectedFloors();
        const excludeIds = this.reviewChallenges
            .filter(c => !c._removed)
            .map(c => c.id)
            .filter(Boolean);

        const btn = document.querySelector(`#review-item-${index} .btn-shuffle`);
        if (btn) { btn.disabled = true; btn.textContent = '...'; }

        try {
            const body = { exclude_ids: excludeIds, difficulty };
            if (selectedFloors) body.floors = selectedFloors;

            const resp = await fetch('/api/challenges/shuffle-one', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });

            if (!resp.ok) {
                const err = await resp.json();
                alert(err.error || 'No more challenges available');
                if (btn) { btn.disabled = false; btn.textContent = 'Shuffle'; }
                return;
            }

            const data = await resp.json();
            this.reviewChallenges[index] = data.challenge;
            this.renderReviewPanel();
        } catch (err) {
            alert('Shuffle failed: ' + err.message);
            if (btn) { btn.disabled = false; btn.textContent = 'Shuffle'; }
        }
    },

    async confirmReviewLaunch() {
        const active = this.reviewChallenges.filter(c => !c._removed);
        if (!active.length) {
            alert('No challenges selected');
            return;
        }

        const challengeIds = active.map(c => c.id).filter(Boolean);
        const btn = document.getElementById('btn-confirm-launch');
        btn.disabled = true;
        btn.textContent = 'Starting...';

        const body = {
            theme: this.selectedTheme,
            rounds: active.length,
            difficulty: document.getElementById('input-difficulty').value,
            test_mode: document.getElementById('input-test-mode').checked,
            test_speaker: document.getElementById('input-test-speaker').value,
            challenge_ids: challengeIds,
        };

        if (this.reviewATVMode) body.appletv_mode = true;

        const haUrl = document.getElementById('input-ha-url').value.trim();
        if (haUrl) body.ha_url = haUrl;
        const hubSpeaker = document.getElementById('input-hub-speaker-select').value;
        if (hubSpeaker) body.hub_speaker = hubSpeaker;

        try {
            const resp = await fetch('/api/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            const data = await resp.json();
            if (data.error) alert(data.error);
        } catch (err) {
            alert('Failed to start: ' + err.message);
        } finally {
            btn.disabled = false;
            btn.textContent = 'Confirm Launch';
            this.cancelReview();
        }
    },

    cancelReview() {
        document.getElementById('review-panel').style.display = 'none';
        this.reviewChallenges = [];
    },

    // --- Floor Management ---
    renderFloorConfig() {
        const list = document.getElementById('floor-config-list');
        if (!list) return;

        // Collect unique areas from allowed speakers
        const areas = [...new Set(this.allowedSpeakers.map(s => s.area).filter(Boolean))];

        if (!this.floors.length) {
            list.innerHTML = '<p class="setup-desc">No floors defined yet.</p>';
            return;
        }

        list.innerHTML = this.floors.map((f, i) => {
            const areaChecks = areas.filter(a => a && a !== 'Unknown').map(a => {
                const checked = (f.areas || []).includes(a) ? 'checked' : '';
                return `<label class="floor-area-toggle"><input type="checkbox" data-floor="${i}" data-area="${a}" ${checked}> ${a}</label>`;
            }).join('');
            return `
                <div class="floor-config-item">
                    <div class="floor-config-header">
                        <input type="text" class="detail-input floor-name-input" data-floor="${i}" value="${f.name || ''}" placeholder="Floor name">
                        <button class="btn-deny btn-small" onclick="App.removeFloor(${i})">Remove</button>
                    </div>
                    <div class="floor-areas">${areaChecks}</div>
                </div>
            `;
        }).join('');
    },

    addFloor() {
        this.floors.push({ name: '', areas: [] });
        this.renderFloorConfig();
    },

    removeFloor(i) {
        this.floors.splice(i, 1);
        this.renderFloorConfig();
        this.renderFloorCheckboxes();
    },

    async saveFloors() {
        // Collect floor data from DOM
        const floors = [];
        const nameInputs = document.querySelectorAll('.floor-name-input');
        nameInputs.forEach((input, i) => {
            const name = input.value.trim();
            if (!name) return;
            const areas = [];
            document.querySelectorAll(`input[data-floor="${i}"][data-area]`).forEach(cb => {
                if (cb.checked) areas.push(cb.dataset.area);
            });
            floors.push({ name, areas });
        });

        try {
            const resp = await fetch('/api/floors', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ floors }),
            });
            if (resp.ok) {
                this.floors = floors;
                this.renderFloorCheckboxes();
            }
        } catch (err) {
            console.error('Save floors failed:', err);
        }
    },

    renderFloorCheckboxes() {
        const group = document.getElementById('floor-filter-group');
        const container = document.getElementById('floor-checkboxes');
        if (!group || !container) return;

        if (!this.floors.length) {
            group.style.display = 'none';
            return;
        }

        group.style.display = 'block';
        container.innerHTML = this.floors.map(f => `
            <label class="floor-checkbox-label">
                <input type="checkbox" class="floor-filter-cb" value="${f.name}" checked>
                <span>${f.name}</span>
            </label>
        `).join('');
    },

    getSelectedFloors() {
        const cbs = document.querySelectorAll('.floor-filter-cb');
        if (!cbs.length) return null;
        const selected = [];
        cbs.forEach(cb => { if (cb.checked) selected.push(cb.value); });
        // If all checked, don't filter
        return selected.length === cbs.length ? null : selected;
    },

    // --- Results ---
    showResults() {
        this.showScreen('results');

        const gs = this.gameState;
        const completed = gs.results.filter(r => r.status === 'completed').length;
        const totalTime = gs.results
            .filter(r => r.status === 'completed')
            .reduce((sum, r) => sum + r.time, 0);

        document.getElementById('results-summary').textContent =
            `${completed} completed in ${Math.round(totalTime)}s`;

        const tbody = document.getElementById('results-tbody');
        tbody.innerHTML = gs.results.map(r => {
            const statusClass = `status-${r.status}`;
            const statusLabel = r.status.charAt(0).toUpperCase() + r.status.slice(1);
            return `
                <tr>
                    <td>${r.round}</td>
                    <td>${r.challenge_name}</td>
                    <td class="time-cell">${r.time}s</td>
                    <td class="${statusClass}">${statusLabel}</td>
                </tr>
            `;
        }).join('');
    },
};

document.addEventListener('DOMContentLoaded', () => App.init());
