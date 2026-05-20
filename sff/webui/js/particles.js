/**
 * SlimeDeals — Bubble & Particle Background System
 * Bulles flottantes translucides, étoiles, connexions — effet premium
 */
(function () {
    'use strict';

    var canvas = document.getElementById('bg-canvas');
    if (!canvas) return;
    var ctx = canvas.getContext('2d');

    // Palette thème
    var PALETTE = [
        { r: 165, g: 233, b: 1   },  // lime
        { r: 97,  g: 31,  b: 176 },  // violet
        { r: 126, g: 200, b: 227 },  // cyan
        { r: 165, g: 233, b: 1   },  // lime (doublé = plus fréquent)
        { r: 200, g: 160, b: 255 },  // lavender
        { r: 251, g: 191, b: 36  },  // amber (rare)
    ];

    var W = 0, H = 0;
    var bubbles = [], stars = [], scanY = 0;
    var raf = null, paused = false;

    /* ── Resize ─────────────────────────────────────────────────── */
    function resize() {
        W = canvas.width  = canvas.offsetWidth  || window.innerWidth;
        H = canvas.height = canvas.offsetHeight || window.innerHeight;
        initStars();
    }

    /* ── Étoiles statiques (minuscules points scintillants) ──────── */
    function initStars() {
        var count = Math.floor(W * H / 6000);
        stars = [];
        for (var i = 0; i < count; i++) {
            stars.push({
                x: Math.random() * W,
                y: Math.random() * H,
                r: 0.5 + Math.random() * 1.0,
                alpha: 0.05 + Math.random() * 0.18,
                twinkle: Math.random() * Math.PI * 2,
                speed: 0.008 + Math.random() * 0.015,
                c: PALETTE[Math.floor(Math.random() * 3)],
            });
        }
    }

    /* ── Bulles flottantes ───────────────────────────────────────── */
    function mkBubble(spreadY) {
        var c = PALETTE[Math.floor(Math.random() * PALETTE.length)];
        var r = 3 + Math.random() * 22;
        return {
            x:     Math.random() * W,
            y:     spreadY !== undefined ? Math.random() * H : H + r + Math.random() * 80,
            r:     r,
            vy:    -(0.12 + Math.random() * 0.35),
            vx:    (Math.random() - 0.5) * 0.15,
            alpha: 0.025 + Math.random() * 0.065,
            c:     c,
            pulse: Math.random() * Math.PI * 2,
            ps:    0.006 + Math.random() * 0.012,
            wobble: Math.random() * Math.PI * 2,
            ws:    0.004 + Math.random() * 0.008,
        };
    }

    function initBubbles() {
        var count = Math.min(40, Math.floor(W * H / 18000) + 18);
        bubbles = [];
        for (var i = 0; i < count; i++) {
            bubbles.push(mkBubble(true));
        }
    }

    /* ── Draw frame ─────────────────────────────────────────────── */
    function draw() {
        if (paused) { raf = null; return; }
        ctx.clearRect(0, 0, W, H);

        /* -- Étoiles -- */
        for (var i = 0; i < stars.length; i++) {
            var s = stars[i];
            s.twinkle += s.speed;
            var a = s.alpha * (0.4 + 0.6 * Math.abs(Math.sin(s.twinkle)));
            ctx.beginPath();
            ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
            ctx.fillStyle = 'rgba(' + s.c.r + ',' + s.c.g + ',' + s.c.b + ',' + a + ')';
            ctx.fill();
        }

        /* -- Bulles -- */
        for (var j = 0; j < bubbles.length; j++) {
            var b = bubbles[j];
            b.pulse  += b.ps;
            b.wobble += b.ws;
            b.y += b.vy;
            b.x += b.vx + Math.sin(b.wobble) * 0.18;

            var rr = b.r + Math.sin(b.pulse) * 1.8;
            var grad = ctx.createRadialGradient(b.x - rr * 0.25, b.y - rr * 0.25, rr * 0.05, b.x, b.y, rr);
            var ao = b.alpha;
            grad.addColorStop(0.0, 'rgba(' + b.c.r + ',' + b.c.g + ',' + b.c.b + ',' + (ao * 1.6) + ')');
            grad.addColorStop(0.55,'rgba(' + b.c.r + ',' + b.c.g + ',' + b.c.b + ',' + ao + ')');
            grad.addColorStop(1.0, 'rgba(' + b.c.r + ',' + b.c.g + ',' + b.c.b + ',0)');

            ctx.beginPath();
            ctx.arc(b.x, b.y, rr, 0, Math.PI * 2);
            ctx.fillStyle = grad;
            ctx.fill();

            // Bord subtil
            ctx.strokeStyle = 'rgba(' + b.c.r + ',' + b.c.g + ',' + b.c.b + ',' + (ao * 0.6) + ')';
            ctx.lineWidth = 0.6;
            ctx.stroke();

            if (b.y < -b.r * 4) {
                bubbles[j] = mkBubble();
            }
        }

        /* -- Ligne de scan horizontale (très subtile, descend lentement) -- */
        scanY = (scanY + 0.18) % H;
        var sg = ctx.createLinearGradient(0, scanY - 60, 0, scanY + 60);
        sg.addColorStop(0,   'rgba(165,233,1,0)');
        sg.addColorStop(0.4, 'rgba(165,233,1,0.012)');
        sg.addColorStop(0.5, 'rgba(165,233,1,0.022)');
        sg.addColorStop(0.6, 'rgba(165,233,1,0.012)');
        sg.addColorStop(1,   'rgba(165,233,1,0)');
        ctx.fillStyle = sg;
        ctx.fillRect(0, scanY - 60, W, 120);

        raf = requestAnimationFrame(draw);
    }

    /* ── Lifecycle ───────────────────────────────────────────────── */
    window.addEventListener('resize', function () {
        resize();
        initBubbles();
    });

    document.addEventListener('visibilitychange', function () {
        paused = document.hidden;
        if (!paused && !raf) draw();
    });

    resize();
    initBubbles();
    draw();
})();
