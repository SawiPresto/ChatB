(function () {
    const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
    const state = {
        token: "",
        game: null,
        config: null,
    };

    const els = {
        level: document.getElementById("level-value"),
        coin: document.getElementById("coin-value"),
        tap: document.getElementById("tap-value"),
        energy: document.getElementById("energy-value"),
        tapBtn: document.getElementById("tap-btn"),
        upgradeBtn: document.getElementById("upgrade-btn"),
        refreshBtn: document.getElementById("refresh-btn"),
        leaderboard: document.getElementById("leaderboard-list"),
        status: document.getElementById("status-text"),
    };

    function setStatus(text) {
        els.status.textContent = text || "";
    }

    function applyState(gameState) {
        if (!gameState) return;
        state.game = gameState;
        els.level.textContent = String(gameState.level);
        els.coin.textContent = String(gameState.coins);
        els.tap.textContent = String(gameState.tap_power);
        els.energy.textContent = `${gameState.energy}/${gameState.max_energy}`;
    }

    async function api(path, method = "GET", body = null, withIdempotency = false) {
        const headers = { "Content-Type": "application/json" };
        if (state.token) headers.Authorization = `Bearer ${state.token}`;
        if (withIdempotency) {
            headers["X-Idempotency-Key"] = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
        }

        const response = await fetch(path, {
            method,
            headers,
            body: body ? JSON.stringify(body) : null,
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(data.error || "Request gagal.");
        }
        return data;
    }

    async function loadLeaderboard() {
        const data = await api("/api/game/leaderboard");
        els.leaderboard.innerHTML = "";
        (data.leaderboard || []).forEach((row) => {
            const li = document.createElement("li");
            li.textContent = `chat ${row.chat_id} - ${row.coins} coin (Lv ${row.level})`;
            els.leaderboard.appendChild(li);
        });
    }

    async function refreshState() {
        const data = await api("/api/game/state");
        applyState(data.state);
    }

    async function handleTap() {
        els.tapBtn.disabled = true;
        try {
            const data = await api("/api/game/tap", "POST", { tap_count: 1 }, true);
            applyState(data.state);
            if (data.tapped) {
                setStatus(`+${data.gained} SawiCoin`);
            } else {
                setStatus("Energy habis atau terlalu cepat tap.");
            }
        } catch (err) {
            setStatus(err.message);
        } finally {
            setTimeout(() => {
                els.tapBtn.disabled = false;
            }, 250);
        }
    }

    async function handleUpgrade() {
        els.upgradeBtn.disabled = true;
        try {
            const data = await api("/api/game/upgrade", "POST", {}, true);
            applyState(data.state);
            if (data.upgraded) {
                setStatus(`Upgrade berhasil. Biaya ${data.cost} coin.`);
            } else {
                setStatus(`Coin kurang. Butuh ${data.cost} coin.`);
            }
        } catch (err) {
            setStatus(err.message);
        } finally {
            els.upgradeBtn.disabled = false;
        }
    }

    async function bootstrap() {
        if (!tg) {
            setStatus("Mini App hanya bisa dibuka dari Telegram.");
            return;
        }

        tg.ready();
        tg.expand();
        setStatus("Menghubungkan akun Telegram...");

        try {
            const auth = await api("/api/game/auth", "POST", { initData: tg.initData });
            state.token = auth.token;
            state.config = auth.config || {};
            applyState(auth.state);
            await loadLeaderboard();
            setStatus("Siap bermain.");
        } catch (err) {
            setStatus(`Auth gagal: ${err.message}`);
        }
    }

    els.tapBtn.addEventListener("click", handleTap);
    els.upgradeBtn.addEventListener("click", handleUpgrade);
    els.refreshBtn.addEventListener("click", async () => {
        try {
            await refreshState();
            await loadLeaderboard();
            setStatus("Data diperbarui.");
        } catch (err) {
            setStatus(err.message);
        }
    });

    setInterval(() => {
        if (!state.token) return;
        refreshState().catch(() => {});
    }, 5000);

    bootstrap();
})();
