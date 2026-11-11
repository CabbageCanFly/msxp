// The live pages' scenery on /local, switched on and off by the player: the town background (odd/even
// day of month, ?background= overrides) and the decorative mobs wandering along the first card (sprites
// credited in README; hover flinches, a click does something random, a rare faded boss drifts behind).
// shortcut: mirrors the background and mob code in product.js; move both into one shared script if either changes.
const MOBS = ['snail', 'blue-snail', 'red-snail', 'shroom', 'slime', 'orange-mushroom', 'ribbon-pig', 'stump', 'green-mushroom', 'lupin', 'pig'];
const BOSSES = ['mano', 'mushmom'];
const pick = (list) => list[Math.floor(Math.random() * list.length)];
const sprite = (slug, action) => `/static/mobs/${slug}-${action}.${slug === 'slime' ? 'webp' : 'gif'}`;  // Soft slime edges need WebP alpha.
const node = (tag, className, text) => Object.assign(document.createElement(tag), className ? {className} : {}, text != null ? {textContent: text} : {});
let lane = null, timer = null, frozen = [];

export function setScenery(on) {
  const body = document.body;
  if (!on) {
    delete body.dataset.background; delete body.dataset.backgroundState;
    clearTimeout(timer); lane?.remove(); lane = null; document.querySelector('.boss')?.remove();
    return;
  }
  if (!body.dataset.background) {
    const chosen = new URLSearchParams(location.search).get('background');
    const town = body.dataset.background = ['sleepywood', 'kerning'].includes(chosen) ? chosen : new Date().getDate() % 2 ? 'sleepywood' : 'kerning';
    body.dataset.backgroundState = 'loading';
    // Revealed once both layers decode; a failed image keeps the navy page.
    Promise.all([`${town}.webp`, town === 'sleepywood' ? 'sleepywood-forest.webp' : 'kerning-sky.webp'].map((file) => Object.assign(new Image(), {src: `/static/${file}`}).decode()))
      .then(() => { if (body.dataset.background === town) body.dataset.backgroundState = 'ready'; }, () => { body.dataset.backgroundState = 'failed'; });
  }
  // Reduced motion: the background only.
  if (lane || matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  lane = node('div', 'mob-lane'); lane.setAttribute('aria-hidden', 'true');
  document.querySelector('.board').before(lane);
  timer = setTimeout(wander, 3000);
}

function spawnBoss() {
  // A steady drift (translate) plus a gentle bob and sway (transform).
  const boss = node('img', 'boss'), ltr = Math.random() < .5, [from, to] = ltr ? [-150, innerWidth + 150] : [innerWidth + 150, -150], y = innerHeight * (.08 + Math.random() * .32);
  boss.src = sprite(pick(BOSSES), 'stand'); boss.alt = ''; document.body.prepend(boss);
  boss.animate([{translate: `${from}px ${y}px`}, {translate: `${to}px ${y + (Math.random() - .5) * 160}px`}], {duration: 28000}).finished.then(() => boss.remove());
  boss.animate([{transform: 'translateY(-14px) rotate(-7deg)'}, {transform: 'translateY(14px) rotate(7deg)'}], {duration: 3200, iterations: Infinity, direction: 'alternate', easing: 'ease-in-out'});
}

function spawnMob(into) {
  const slug = pick(MOBS), mob = node('div', 'mob'), img = node('img');
  img.alt = ''; img.draggable = false; img.src = sprite(slug, 'move'); mob.append(img);
  img.decode().then(() => {
    if (document.hidden || lane !== into || into.querySelectorAll('.mob').length >= 3) return;
    into.append(mob);
    // Sprites face left, so walking right mirrors the mob. It walks until half its body hangs over the card's edge.
    const half = img.naturalWidth / 2, width = into.clientWidth, right = Math.random() < .5;
    const at = (f) => `translateX(${right ? half + f * (width - half) : (width - half) * (1 - f)}px) scaleX(${right ? -1 : 1})`;
    const walk = mob.animate([{transform: at(0)}, {transform: at(1)}], {duration: (width - half) / (25 + Math.random() * 15) * 1000, fill: 'forwards'});
    let gone = false;
    const end = (frames, duration) => { gone = true; walk.pause(); img.style.pointerEvents = 'none'; img.animate(frames, {duration, easing: 'ease-in', fill: 'forwards'}).finished.then(() => mob.remove()); };
    const fall = () => { img.src = sprite(slug, 'hit'); end([{transform: 'none'}, {transform: `translate(-${half + 10}px,260px) rotate(-110deg)`, opacity: 0}], 900); };
    const die = () => { img.src = sprite(slug, 'die'); end([{opacity: 1}, {opacity: 1, offset: .6}, {opacity: 0}], 1100); };
    const hop = () => img.animate([{transform: 'none'}, {transform: 'translateY(-28px)'}, {transform: 'none'}], {duration: 450, easing: 'ease-out'});
    const reactions = [() => walk.updatePlaybackRate(3), hop, fall, die];
    walk.finished.then(() => { if (!gone) fall(); });
    img.addEventListener('pointerenter', () => {
      if (gone || walk.playState !== 'running') return;
      walk.pause(); img.src = sprite(slug, 'hit');
      setTimeout(() => { if (!gone) { img.src = sprite(slug, 'move'); walk.play(); } }, 500);
    });
    img.addEventListener('click', () => {
      if (gone) return;
      const hit = node('span', 'mob-hit', String(7 + Math.floor(Math.random() * 40)));
      hit.style.left = `${mob.getBoundingClientRect().left - into.getBoundingClientRect().left}px`; hit.style.bottom = `${img.height + 4}px`;
      into.append(hit); setTimeout(() => hit.remove(), 1000);
      pick(reactions)();
    });
  }, () => {});  // A sprite that fails to load is simply skipped.
}

// Every 10-45 s: occasionally a boss (one at a time), otherwise a mob, at most 3 at once.
function wander() {
  if (!lane) return;
  if (!document.hidden) {
    if (Math.random() < 1 / 12 && !document.querySelector('.boss')) spawnBoss();
    else if (lane.querySelectorAll('.mob').length < 3) spawnMob(lane);
  }
  timer = setTimeout(wander, 10000 + Math.random() * 35000);
}

// A background tab freezes motion (zero speed also stops a hover from restarting it) and restores it after.
document.addEventListener('visibilitychange', () => {
  if (document.hidden) {
    const animations = [...(lane?.getAnimations({subtree: true}) ?? []), ...(document.querySelector('.boss')?.getAnimations() ?? [])];
    frozen = animations.filter((a) => a.playState === 'running' || a.playState === 'paused').map((a) => [a, a.playbackRate]);
    frozen.forEach(([a]) => { a.playbackRate = 0; });
  } else { frozen.forEach(([a, rate]) => { a.playbackRate = rate; }); frozen = []; }
});
