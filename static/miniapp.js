(function () {
    const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
    const state = {
        token: "",
        game: null,
        catalog: [],
        config: {},
    };

    const els = {
        level: document.getElementById("level-value"),
        coin: document.getElementById("coin-value"),
        tap: document.getElementById("tap-value"),
        energy: document.getElementById("energy-value"),
        weaponSlot: document.getElementById("weapon-slot"),
        petSlot: document.getElementById("pet-slot"),
        skinSlot: document.getElementById("skin-slot"),
        weaponVisual: document.getElementById("weapon-visual"),
        charFallback: document.getElementById("char-fallback"),
        charArt: document.getElementById("char-art"),
        charBaseImg: document.getElementById("char-base-img"),
        charSkinImg: document.getElementById("char-skin-img"),
        charWeaponImg: document.getElementById("char-weapon-img"),
        charPetImg: document.getElementById("char-pet-img"),
        tapBtn: document.getElementById("tap-btn"),
        upgradeBtn: document.getElementById("upgrade-btn"),
        refreshBtn: document.getElementById("refresh-btn"),
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

    function setWeaponVisual(weaponId) {
        const node = els.weaponVisual;
        node.classList.remove("weapon-none", "weapon-bamboo", "weapon-shadow", "weapon-quantum");
        if (!weaponId) {
            node.classList.add("weapon-none");
            return;
        }
        if (weaponId === "weapon_bamboo_spear") node.classList.add("weapon-bamboo");
        else if (weaponId === "weapon_shadow_blade") node.classList.add("weapon-shadow");
        else if (weaponId === "weapon_quantum_cleaver") node.classList.add("weapon-quantum");
        else node.classList.add("weapon-none");
    }

    function setImgIfExists(node, src) {
        if (!node) return;
        if (!src) {
            node.removeAttribute("src");
            node.style.display = "none";
            return;
        }
        node.src = src;
        node.style.display = "block";
    }

    function applyCharacterArt(gameState) {
        const baseAsset = state.config.character_base_asset || "";
        const skinAsset = gameState && gameState.equipment && gameState.equipment.skin ? gameState.equipment.skin.asset : "";
        const weaponAsset = gameState && gameState.equipment && gameState.equipment.weapon ? gameState.equipment.weapon.asset : "";
        const petAsset = gameState && gameState.equipment && gameState.equipment.pet ? gameState.equipment.pet.asset : "";

        const hasAny = Boolean(baseAsset || skinAsset || weaponAsset || petAsset);
        if (!hasAny) {
            els.charArt.classList.remove("active");
            els.charFallback.style.display = "block";
            return;
        }

        setImgIfExists(els.charBaseImg, baseAsset);
        setImgIfExists(els.charSkinImg, skinAsset);
        setImgIfExists(els.charWeaponImg, weaponAsset);
        setImgIfExists(els.charPetImg, petAsset);
        els.charArt.classList.add("active");
        els.charFallback.style.display = "none";
    }

    function applyState(gameState) {
        if (!gameState) return;
        state.game = gameState;
        els.level.textContent = String(gameState.level);
        els.coin.textContent = String(gameState.coins);
        els.tap.textContent = String(gameState.effective_tap_power || gameState.tap_power);
        els.energy.textContent = `${gameState.effective_energy}/${gameState.effective_max_energy}`;
        els.weaponSlot.textContent = getEquipmentName(gameState.equipment && gameState.equipment.weapon);
        els.petSlot.textContent = getEquipmentName(gameState.equipment && gameState.equipment.pet);
        els.skinSlot.textContent = getEquipmentName(gameState.equipment && gameState.equipment.skin);
        setWeaponVisual(gameState.weapon_id);
        applyCharacterArt(gameState);
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
            setStatus(data.tapped ? `+${data.gained} coin` : "Energy habis atau tap terlalu cepat.");
        } catch (err) {
            setStatus(err.message);
        } finally {
            setTimeout(() => {
                els.tapBtn.disabled = false;
            }, 220);
        }
    }

    async function handleUpgrade() {
        els.upgradeBtn.disabled = true;
        try {
            const data = await api("/api/game/upgrade", "POST", {}, true);
            applyState(data.state);
            renderShop();
            setStatus(data.upgraded ? `Upgrade sukses. Biaya ${data.cost}.` : `Coin kurang. Butuh ${data.cost}.`);
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
        setStatus("Sinkronisasi akun...");
        try {
            const auth = await api("/api/game/auth", "POST", { initData: tg.initData });
            state.token = auth.token;
            state.catalog = Array.isArray(auth.catalog) ? auth.catalog : [];
            state.config = auth.config || {};
            applyState(auth.state);
            renderShop();
            await loadLeaderboard();
            setStatus("SawiPresto Revenge siap dimainkan.");
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
