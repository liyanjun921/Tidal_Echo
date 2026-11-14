/* One wallpaper texture and one WebGL context for visible liquid-glass surfaces.
   Draw only when the wallpaper, layout or scroll position changes. */
(() => {
  'use strict';
  const phone = document.getElementById('emoiPhone');
  if (!phone) return;
  const mobile = matchMedia('(pointer: coarse)');
  const forced = matchMedia('(forced-colors: active)');
  const reduced = matchMedia('(prefers-reduced-transparency: reduce)');
  const targets = new Map();
  let image, source, engine, frame = 0;

  const vertex = `
    attribute vec2 position;
    varying vec2 uv;
    void main() {
      uv = vec2(position.x + 1.0, 1.0 - position.y) * 0.5;
      gl_Position = vec4(position, 0.0, 1.0);
    }`;
  const fragment = `
    precision highp float;
    varying vec2 uv;
    uniform sampler2D wallpaper;
    uniform vec4 crop;
    uniform vec2 size;
    uniform float radius, depth;
    float roundBox(vec2 p, vec2 halfSize, float r) {
      vec2 q = abs(p) - halfSize + r;
      return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r;
    }
    void main() {
      vec2 p = (uv - 0.5) * size;
      vec2 halfSize = size * 0.5;
      float r = min(radius, min(halfSize.x, halfSize.y));
      float d = roundBox(p, halfSize, r);
      vec2 n = vec2(roundBox(p + vec2(0.5, 0.0), halfSize, r) - d,
                    roundBox(p + vec2(0.0, 0.5), halfSize, r) - d);
      n = normalize(n + vec2(0.0001));
      float edgeWidth = min(38.0, min(size.x, size.y) / 3.5);
      float bevel = clamp(1.0 + d / edgeWidth, 0.0, 1.0);
      float wave = sin(uv.y * 12.0 + uv.x * 3.0) * cos(uv.x * 8.0);
      vec2 shift = -n * pow(bevel, 2.6) * depth
                   + (uv - 0.5) * 0.55 + vec2(wave, -wave) * (0.12 + 0.4 * bevel);
      vec2 uvShift = shift / size * crop.zw;
      vec2 base = crop.xy + uv * crop.zw;
      vec3 c = vec3(texture2D(wallpaper, base + uvShift * 1.09).r,
                    texture2D(wallpaper, base + uvShift).g,
                    texture2D(wallpaper, base + uvShift * 0.94).b);
      float light = dot(n, normalize(vec2(-0.65, -1.0)));
      float rim = (d + 1.1) / 0.72;
      float shoulder = (d + 3.3) / 1.65;
      float glint = exp(-rim * rim);
      float inner = exp(-shoulder * shoulder);
      c = mix(c * (1.0 - inner * 0.12), vec3(1.0),
        glint * (0.13 + 0.47 * max(light, 0.0) + 0.16 * max(-light, 0.0)));
      float opacity = (0.04 + 0.83 * bevel) * (1.0 - smoothstep(-1.2, 0.25, d));
      gl_FragColor = vec4(c, opacity);
    }`;

  function createRenderer() {
    const canvas = document.createElement('canvas');
    const gl = canvas.getContext('webgl', {alpha: true, premultipliedAlpha: false, depth: false, antialias: false, preserveDrawingBuffer: true});
    if (!gl) return null;
    const program = gl.createProgram();
    for (const [type, code] of [[gl.VERTEX_SHADER, vertex], [gl.FRAGMENT_SHADER, fragment]]) {
      const shader = gl.createShader(type);
      gl.shaderSource(shader, code);
      gl.compileShader(shader);
      if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) return null;
      gl.attachShader(program, shader);
      gl.deleteShader(shader);
    }
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) return null;
    gl.useProgram(program);
    gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1, 1,-1, -1,1, 1,1]), gl.STATIC_DRAW);
    const position = gl.getAttribLocation(program, 'position');
    gl.enableVertexAttribArray(position);
    gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0);
    gl.bindTexture(gl.TEXTURE_2D, gl.createTexture());
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    const uniforms = Object.fromEntries(['crop', 'size', 'radius', 'depth'].map(key => [key, gl.getUniformLocation(program, key)]));
    canvas.addEventListener('webglcontextlost', event => {
      event.preventDefault();
      clearLenses();
    });
    canvas.addEventListener('webglcontextrestored', () => { engine = undefined; source = undefined; schedule(); });
    return {canvas, gl, uniforms, uploaded: null};
  }

  function clearLenses() {
    for (const [target, layer] of targets) {
      layer.remove();
      delete target.dataset.epOpticsReady;
    }
    targets.clear();
  }

  function loadWallpaper(css) {
    source = css;
    image = null;
    clearLenses();
    const match = /^url\((?:"([^"]+)"|'([^']+)'|([^)]*))\)$/.exec(css);
    if (!match) return;
    const incoming = new Image();
    incoming.onload = () => {
      if (source !== css) return;
      image = incoming;
      schedule();
    };
    incoming.src = match[1] || match[2] || match[3];
  }

  function layout(box) {
    const scale = Math.max(box.width / image.naturalWidth, box.height / image.naturalHeight);
    const width = image.naturalWidth * scale, height = image.naturalHeight * scale;
    return {width, height, left: (box.width - width) / 2, top: (box.height - height) / 2};
  }

  function render() {
    const page = [...document.querySelectorAll('.page-sheet[open], #wrenRoom[open]')].at(-1);
    const home = document.body.dataset.phoneScreen === 'home';
    const override = document.body.dataset.pageGlass;
    const material = override || document.documentElement.dataset.glass;
    if (forced.matches || reduced.matches || material === 'frost' || document.body.dataset.uiMode !== 'phone' || (!page && !home)) {
      clearLenses();
      return;
    }
    const sceneRoot = page || phone;
    const style = getComputedStyle(sceneRoot, page ? null : '::before');
    const imageLayer = [...style.backgroundImage.matchAll(/url\((?:"[^"]*"|'[^']*'|[^)]*)\)/g)].at(-1)?.[0];
    if (!imageLayer) { clearLenses(); return; }
    if (source !== imageLayer) loadWallpaper(imageLayer);
    const box = sceneRoot.getBoundingClientRect();
    if (!box.width || !box.height) return;
    const nodes = [...sceneRoot.querySelectorAll(page
      ? '.calendar-month-card, .calendar-detail, .entry-card, .sheet-head'
      : '[data-ep-optics]')];
    if (!image) return;
    const scene = layout(box);
    if (engine === undefined) engine = createRenderer();
    if (!engine || engine.gl.isContextLost()) return;
    const {canvas, gl, uniforms} = engine;
    if (engine.uploaded !== image) {
      try {
        let texture = image;
        const scale = Math.min(1, Math.min(gl.getParameter(gl.MAX_TEXTURE_SIZE), 2048) / Math.max(image.naturalWidth, image.naturalHeight));
        if (scale < 1) {
          texture = document.createElement('canvas');
          texture.width = Math.max(1, Math.round(image.naturalWidth * scale));
          texture.height = Math.max(1, Math.round(image.naturalHeight * scale));
          texture.getContext('2d').drawImage(image, 0, 0, texture.width, texture.height);
        }
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, texture);
      } catch { clearLenses(); return; }
      engine.uploaded = image;
    }
    const active = nodes.map(node => ({node, rect: node.getBoundingClientRect()}))
      .filter(({rect}) => rect.width >= 32 && rect.height >= 32 && rect.bottom > box.top && rect.top < box.bottom);
    if (mobile.matches && page) active.splice(6);
    for (const [node, layer] of targets) {
      if (!active.some(item => item.node === node)) {
        layer.remove();
        delete node.dataset.epOpticsReady;
        targets.delete(node);
      }
    }
    if (!active.length) return;
    const scale = Math.min(devicePixelRatio || 1, mobile.matches ? 1 : 1.5);
    const width = Math.max(...active.map(({rect}) => Math.ceil(rect.width * scale)));
    const height = Math.max(...active.map(({rect}) => Math.ceil(rect.height * scale)));
    if (canvas.width !== width) canvas.width = width;
    if (canvas.height !== height) canvas.height = height;
    for (const {node, rect} of active) {
      const w = Math.ceil(rect.width * scale), h = Math.ceil(rect.height * scale);
      let layer = targets.get(node);
      if (!layer) {
        if (page) node.classList.add('ep-page-optic');
        layer = document.createElement('canvas');
        layer.className = 'ep-optical-canvas';
        layer.setAttribute('aria-hidden', 'true');
        node.prepend(layer);
        targets.set(node, layer);
      }
      if (layer.width !== w) layer.width = w;
      if (layer.height !== h) layer.height = h;
      gl.viewport(0, 0, w, h);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.uniform4f(uniforms.crop, (rect.left - box.left - scene.left) / scene.width,
        (rect.top - box.top - scene.top) / scene.height, rect.width / scene.width, rect.height / scene.height);
      gl.uniform2f(uniforms.size, rect.width, rect.height);
      gl.uniform1f(uniforms.radius, parseFloat(getComputedStyle(node).borderTopLeftRadius) || 0);
      gl.uniform1f(uniforms.depth, Math.min(41, Math.min(rect.width, rect.height) * 0.30));
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
      const ctx = layer.getContext('2d');
      ctx.clearRect(0, 0, w, h);
      ctx.drawImage(canvas, 0, canvas.height - h, w, h, 0, 0, w, h);
      node.dataset.epOpticsReady = '1';
    }
  }

  function schedule() {
    if (frame || document.hidden) return;
    frame = requestAnimationFrame(() => { frame = 0; render(); });
  }

  const observer = new MutationObserver(mutations => {
    if (mutations.some(record => record.type === 'attributes' ||
      [...record.addedNodes, ...record.removedNodes].some(node => node.nodeName !== 'CANVAS'))) schedule();
  });
  observer.observe(document.body, {childList: true, subtree: true, attributes:true, attributeFilter:['open']});
  observer.observe(document.body, {attributes: true, attributeFilter: ['data-ui-mode', 'data-phone-screen', 'data-emoi-wall', 'class', 'data-page-glass', 'data-dark']});
  observer.observe(document.documentElement, {attributes: true, attributeFilter: ['style', 'data-theme', 'data-glass']});
  if (window.ResizeObserver) new ResizeObserver(schedule).observe(phone);
  reduced.addEventListener('change', schedule);
  window.addEventListener('resize', schedule, {passive: true});
  document.addEventListener('scroll', schedule, {passive: true, capture: true});
  document.addEventListener('visibilitychange', schedule);
  forced.addEventListener?.('change', schedule);
  schedule();
})();
