(function () {
    const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
    const state = {
        token: "",
        game: null,
        catalog: [],
        config: {},
    };

    const els = {
        sceneBg: document.getElementById("scene-bg"),
        playerName: document.getElementById("player-name"),
        level: document.getElementById("level-value"),
        coin: document.getElementById("coin-value"),
        levelProgressBar: document.getElementById("level-progress-bar"),
        levelProgressText: document.getElementById("level-progress-text"),
        energy: document.getElementById("energy-value"),
        energyBar: document.getElementById("energy-bar"),
        tap: document.getElementById("tap-value"),
        tapBar: document.getElementById("tap-bar"),
        enemyName: document.getElementById("enemy-name"),
        enemyLevel: document.getElementById("enemy-level"),
        enemyHpBar: document.getElementById("enemy-hp-bar"),
        enemyHpValue: document.getElementById("enemy-hp-value"),
        weaponSlot: document.getElementById("weapon-slot"),
        petSlot: document.getElementById("pet-slot"),
        skinSlot: document.getElementById("skin-slot"),
        charFallback: document.getElementById("char-fallback"),
        enemyFallback: document.getElementById("enemy-fallback"),
        charBaseImg: document.getElementById("char-base-img"),
        charSkinImg: document.getElementById("char-skin-img"),
        charWeaponImg: document.getElementById("char-weapon-img"),
        charPetImg: document.getElementById("char-pet-img"),
        enemyBaseImg: document.getElementById("enemy-base-img"),
        playerFighter: document.getElementById("player-fighter"),
        enemyFighter: document.getElementById("enemy-fighter"),
        slashFx: document.getElementById("slash-fx"),
        hitFx: document.getElementById("hit-fx"),
        damageLayer: document.getElementById("damage-layer"),
        tapBtn: document.getElementById("tap-btn"),
        upgradeBtn: document.getElementById("upgrade-btn"),
        inventoryBtn: document.getElementById("inventory-btn"),
        leaderboardBtn: document.getElementById("leaderboard-btn"),
        refreshBtn: document.getElementById("refresh-btn"),
        inventoryPanel: document.getElementById("inventory-panel"),
        closeInventory: document.getElementById("close-inventory"),
        leaderboardPanel: document.getElementById("leaderboard-panel"),
        closeLeaderboard: document.getElementById("close-leaderboard"),
        leaderboard: document.getElementById("leaderboard-list"),
        shopGrid: document.getElementById("shop-grid"),
        status: document.getElementById("status-text"),
    };

    function setStatus(text) {
        els.status.textContent = text || "";
    }

    function getEquipmentName(equipment) {
        return equipment && equipment.name ? equipment.name : "None";
    }

    function setImg(node, src, fallbackNode) {
        if (!node) return;
        if (!src) {
            node.removeAttribute("src");
            node.style.display = "none";
            if (fallbackNode) fallbackNode.style.display = "block";
            return;
        }
        node.src = src;
        node.style.display = "block";
        node.onerror = function () {
            node.style.display = "none";
            if (fallbackNode) fallbackNode.style.display = "block";
        };
        node.onload = function () {
            if (fallbackNode) fallbackNode.style.display = "none";
        };
    }

    function applySceneConfig() {
        if (state.config.battle_bg_asset) {
            els.sceneBg.style.backgroundImage = `url('${state.config.battle_bg_asset}')`;
        } else {
            els.sceneBg.style.backgroundImage =
                "radial-gradient(circle at 50% 30%, #2e7d32, #0b3a22 55%, #082116)";
        }
        const initialEnemyAsset = state.config.enemy_base_asset || "";
        setImg(els.enemyBaseImg, initialEnemyAsset, els.enemyFallback);
    }

    function spawnDamage(value) {
        const node = document.createElement("span");
        node.className = "damage";
        node.textContent = String(value);
        node.style.left = `${62 + Math.random() * 12}%`;
        node.style.top = `${42 + Math.random() * 10}%`;
        els.damageLayer.appendChild(node);
        setTimeout(() => {
            node.remove();
        }, 820);
    }

    function triggerAttackFx(damage) {
        els.playerFighter.classList.add("attacking");
        els.enemyFighter.classList.add("hit");
        els.slashFx.classList.add("active");
        els.hitFx.classList.add("active");
        if (damage > 0) {
            spawnDamage(damage);
        }
        setTimeout(() => {
            els.playerFighter.classList.remove("attacking");
            els.enemyFighter.classList.remove("hit");
            els.slashFx.classList.remove("active");
            els.hitFx.classList.remove("active");
        }, 260);
    }

    function applyCharacterArt(gameState) {
        const baseAsset = state.config.character_base_asset || "";
        const skinAsset = gameState && gameState.equipment && gameState.equipment.skin ? gameState.equipment.skin.asset : "";
        const weaponAsset = gameState && gameState.equipment && gameState.equipment.weapon ? gameState.equipment.weapon.asset : "";
        const petAsset = gameState && gameState.equipment && gameState.equipment.pet ? gameState.equipment.pet.asset : "";
        setImg(els.charBaseImg, baseAsset, els.charFallback);
        setImg(els.charSkinImg, skinAsset);
        setImg(els.charWeaponImg, weaponAsset);
        setImg(els.charPetImg, petAsset);
    }

    function applyState(gameState) {
        if (!gameState) return;
        state.game = gameState;

        const level = Number(gameState.level || 1);
        const coins = Number(gameState.coins || 0);
        const effectiveTap = Number(gameState.effective_tap_power || gameState.tap_power || 1);
        const effectiveEnergy = Number(gameState.effective_energy || 0);
        const effectiveMaxEnergy = Number(gameState.effective_max_energy || gameState.max_energy || 1);

        els.level.textContent = String(level);
        els.coin.textContent = String(coins);
        const username = String(gameState.player_username || "").trim();
        const displayName = username
            ? `@${username}`
            : (String(gameState.player_name || "").trim() || "Player");
        els.playerName.textContent = displayName;
        els.tap.textContent = String(effectiveTap);
        els.energy.textContent = `${effectiveEnergy}/${effectiveMaxEnergy}`;

        const energyPercent = Math.max(0, Math.min(100, (effectiveEnergy / Math.max(1, effectiveMaxEnergy)) * 100));
        els.energyBar.style.width = `${energyPercent}%`;
        const tapPercent = Math.max(8, Math.min(100, effectiveTap * 4));
        els.tapBar.style.width = `${tapPercent}%`;
        const progress = gameState.level_progress || {};
        const progressCurrent = Number(progress.current || 0);
        const progressTarget = Math.max(1, Number(progress.target || 1));
        const progressPct = Math.max(0, Math.min(100, (progressCurrent / progressTarget) * 100));
        els.levelProgressBar.style.width = `${progressPct}%`;
        els.levelProgressText.textContent = `${progressCurrent}/${progressTarget}`;

        const enemy = gameState.enemy || {};
        const enemyHp = Number(enemy.hp || 0);
        const enemyMaxHp = Number(enemy.max_hp || 1);
        const enemyPct = Math.max(0, Math.min(100, (enemyHp / Math.max(1, enemyMaxHp)) * 100));
        els.enemyName.textContent = enemy.name || "Enemy";
        els.enemyLevel.textContent = String(enemy.level || 1);
        els.enemyHpValue.textContent = `${enemyHp}/${enemyMaxHp}`;
        els.enemyHpBar.style.width = `${enemyPct}%`;
        setImg(
            els.enemyBaseImg,
            enemy.asset || state.config.enemy_base_asset || "",
            els.enemyFallback
        );

        els.weaponSlot.textContent = getEquipmentName(gameState.equipment && gameState.equipment.weapon);
        els.petSlot.textContent = getEquipmentName(gameState.equipment && gameState.equipment.pet);
        els.skinSlot.textContent = getEquipmentName(gameState.equipment && gameState.equipment.skin);

        applyCharacterArt(gameState);
    }

    function togglePanel(panel, forceOpen) {
        const open = typeof forceOpen === "boolean" ? forceOpen : panel.classList.contains("hidden");
        if (open) panel.classList.remove("hidden");
        else panel.classList.add("hidden");
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
            li.textContent = `${row.name || ("chat " + row.chat_id)} - ${row.coins} coin (Lv ${row.level})`;
            els.leaderboard.appendChild(li);
        });
    }

    function renderShop() {
        const owned = new Set((state.game && state.game.owned_items) || []);
        els.shopGrid.innerHTML = "";
        state.catalog.forEach((item) => {
            const card = document.createElement("article");
            card.className = "shop-card";
            const isOwned = owned.has(item.id);
            card.innerHTML = `
                <h3>${item.name}</h3>
                ${item.asset ? `<img class="item-thumb" src="${item.asset}" alt="${item.name}">` : ""}
                <div class="shop-meta">Type: ${item.type}</div>
                <div class="shop-meta">Tap +${item.tap_bonus} | Energy +${item.energy_bonus}</div>
                <div class="shop-meta">Harga: ${item.price} coin</div>
            `;
            const btn = document.createElement("button");
            btn.className = `buy-btn${isOwned ? " owned" : ""}`;
            btn.textContent = isOwned ? "Owned" : "Buy & Equip";
            btn.disabled = isOwned;
            btn.addEventListener("click", () => buyItem(item.id));
            card.appendChild(btn);
            els.shopGrid.appendChild(card);
        });
    }

    async function refreshState() {
        const data = await api("/api/game/state");
        applyState(data.state);
        renderShop();
    }

    async function buyItem(itemId) {
        try {
            const data = await api("/api/game/buy", "POST", { item_id: itemId }, true);
            applyState(data.state);
            if (Array.isArray(data.catalog)) {
                state.catalog = data.catalog;
            }
            renderShop();
            setStatus(data.message || (data.bought ? "Item dibeli." : "Pembelian gagal."));
        } catch (err) {
            setStatus(err.message);
        }
    }

    async function handleTap() {
        els.tapBtn.disabled = true;
        try {
            const data = await api("/api/game/tap", "POST", { tap_count: 1 }, true);
            applyState(data.state);
            renderShop();
            if (data.tapped) {
                triggerAttackFx(data.damage || data.gained);
                if (data.enemy_defeated) {
                    const enemyInfo = data.state && data.state.enemy ? data.state.enemy : null;
                    const levelInfo = data.enemy_level_up && enemyInfo
                        ? ` Musuh baru: ${enemyInfo.name} (Lv ${enemyInfo.level}).`
                        : " Boss terakhir respawn lagi.";
                    setStatus(`Enemy down! +${data.gained} coin.${levelInfo}`);
                } else {
                    setStatus(`Critical slash! ${data.damage} dmg, +${data.gained} coin`);
                }
            } else {
                setStatus("Energy habis atau tap terlalu cepat.");
            }
        } catch (err) {
            setStatus(err.message);
        } finally {
            setTimeout(() => {
                els.tapBtn.disabled = false;
            }, 180);
        }
    }

    async function handleUpgrade() {
        els.upgradeBtn.disabled = true;
        try {
            const data = await api("/api/game/upgrade", "POST", {}, true);
            applyState(data.state);
            renderShop();
            setStatus(data.upgraded ? `Level up berhasil. Biaya ${data.cost}.` : `Coin kurang. Butuh ${data.cost}.`);
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
        setStatus("Memuat arena battle...");

        try {
            const auth = await api("/api/game/auth", "POST", { initData: tg.initData });
            state.token = auth.token;
            state.catalog = Array.isArray(auth.catalog) ? auth.catalog : [];
            state.config = auth.config || {};

            applySceneConfig();
            applyState(auth.state);
            renderShop();
            await loadLeaderboard();

            setStatus("Arena siap. Tap untuk menyerang!");
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
            setStatus("Sinkronisasi sukses.");
        } catch (err) {
            setStatus(err.message);
        }
    });

    els.inventoryBtn.addEventListener("click", () => {
        togglePanel(els.inventoryPanel);
        togglePanel(els.leaderboardPanel, false);
    });
    els.leaderboardBtn.addEventListener("click", async () => {
        togglePanel(els.leaderboardPanel);
        togglePanel(els.inventoryPanel, false);
        if (!els.leaderboardPanel.classList.contains("hidden")) {
            try {
                await loadLeaderboard();
            } catch (_) {}
        }
    });
    els.closeInventory.addEventListener("click", () => togglePanel(els.inventoryPanel, false));
    els.closeLeaderboard.addEventListener("click", () => togglePanel(els.leaderboardPanel, false));

    setInterval(() => {
        if (!state.token) return;
        refreshState().catch(() => {});
    }, 4500);

    bootstrap();
})();
