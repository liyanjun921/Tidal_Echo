/* Émoi Archive Glass: wallpaper per chat room and per feature page.
   Preset selections are saved locally; private photo bytes never leave the device. */
(() => {
  'use strict';

  const STORAGE_KEY = 'emoi-wallpapers-v1';
  const DB_NAME = 'emoi-ui-assets';
  const FILE_STORE = 'files';
  const MAX_BYTES = 12 * 1024 * 1024;
  const IMAGES = new Set(['image/jpeg', 'image/png', 'image/webp', 'image/avif', 'image/heic', 'image/heif']);

  const PRESETS = [
    {id:'inherit', name:'跟随全局', caption:'沿用外观设置', value:null},
    {id:'aura', name:'珍珠蓝光', caption:'液态玻璃 · 雾白蓝', value:"url('assets/emoi-phone-aura.svg')"},
    {id:'archive', name:'植物档案', caption:'雾蓝 · 纸张 · 红线', value:"url('assets/emoi-archive-botanical.svg')"},
    {id:'nocturne', name:'星轨夜色', caption:'深蓝 · 轨道 · 微光', value:"url('assets/emoi-archive-nocturne.svg')"},
    {id:'water', name:'流动水光', caption:'清透的蓝色', value:"url('assets/water-light.webp')"},
    {id:'lily', name:'百合晨雾', caption:'柔软的白与蓝', value:"url('assets/lily-water.webp')"},
    {id:'paper', name:'空白画纸', caption:'自由留白', value:'linear-gradient(135deg,#e3e9ec,#f4f4f1 52%,#d8e1e9)'}
  ];

  const LABELS = {
    home:'小手机桌面', messages:'信息', contacts:'通讯录', memory:'记忆档案', todo:'定时清单', calendar:'日历',
    journal:'生活日记', whisper:'悄悄话', reading:'共读书房',
    cinema:'双人影院', report:'日报', health:'健康记录',
    repo:'仓库', appearance:'外观', search:'搜索', capacity:'上下文',
    gpt:'GPT 私聊', claude:'Claude 私聊', group:'三人聊天室'
  };
  const DEFAULTS = {
    'page:home':'lily', 'page:contacts':'lily', 'page:messages':'lily', 'page:memory':'archive', 'page:reading':'archive', 'page:journal':'archive',
    'page:cinema':'nocturne', 'page:report':'archive',
    'page:whisper':'archive', 'page:health':'lily',
    'page:calendar':'water', 'page:todo':'water'
  };
  const safeRead = (name, fallback) => {
    try {
      const data = JSON.parse(localStorage.getItem(name));
      return data && typeof data === 'object' && !Array.isArray(data) ? data : fallback;
    } catch (_) { return fallback; }
  };
  const settings = safeRead(STORAGE_KEY, {});
  let activeContext = 'chat:gpt';
  let lastChat = 'chat:gpt';
  let revision = 0;
  let activeObjectURL = null;
  let picker = null;
  let pickerStatus = null;
  let pickerGrid = null;
  let uploadInput = null;

  function contextName(key) {
    const parts = key.split(':');
    return (LABELS[parts[1]] || parts[1] || '当前页面') + ' · 专属壁纸';
  }
  function selected(key) {
    if (Object.prototype.hasOwnProperty.call(settings, key)) {
      const choice = settings[key];
      return choice === 'custom' || PRESETS.some(item=>item.id===choice) ? choice : 'inherit';
    }
    // Respect the older appearance setting when it was changed deliberately.
    const oldTheme = safeRead('emoi-v05-preferences', {}).theme;
    if (oldTheme && oldTheme !== 'water') return 'inherit';
    return DEFAULTS[key] || (key.startsWith('chat:contact:') || key.startsWith('chat:group:') ? 'lily' : key.startsWith('chat:') ? 'archive' : 'inherit');
  }
  function saveSettings() {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(settings)); return true; }
    catch (_) { return false; }
  }
  function openDB() {
    return new Promise((resolve, reject) => {
      if (!window.indexedDB) { reject(new Error('当前浏览器未提供本地图片存储')); return; }
      const request = indexedDB.open(DB_NAME, 1);
      request.onupgradeneeded = () => {
        if (!request.result.objectStoreNames.contains(FILE_STORE)) request.result.createObjectStore(FILE_STORE);
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error || new Error('本机图片存储失败'));
      request.onblocked = () => reject(new Error('请关闭其他 Émoi 页面后重试'));
    });
  }
  async function fileOperation(key, value, write = false) {
    // Legacy migration must finish before the first read/write to avoid racing.
    await Promise.resolve(window.EmoiLegacyStorageReady);
    const db = await openDB();
    try {
      return await new Promise((resolve, reject) => {
        const transaction = db.transaction(FILE_STORE, write ? 'readwrite' : 'readonly');
        const request = write ? transaction.objectStore(FILE_STORE).put(value, key)
                              : transaction.objectStore(FILE_STORE).get(key);
        request.onerror = () => reject(request.error || new Error('无法读取壁纸'));
        transaction.onerror = () => reject(transaction.error || new Error('保存壁纸失败'));
        transaction.onabort = () => reject(transaction.error || new Error('存储已取消'));
        transaction.oncomplete = () => resolve(write ? true : request.result);
      });
    } finally { db.close(); }
  }
  function clearObjectURL() {
    if (activeObjectURL) URL.revokeObjectURL(activeObjectURL);
    activeObjectURL = null;
  }
  function setBackground(value, key) {
    document.documentElement.style.setProperty('--emoi-active-wallpaper', value || 'var(--wallpaper)');
    document.body.dataset.emoiWall = key;
  }
  async function activate(key) {
    if (!/^(chat:(gpt|claude|group|(?:contact|group):[0-9a-fA-F-]{36})|page:[a-z]+)$/.test(key)) return;
    activeContext = key;
    if (key.startsWith('chat:')) lastChat = key;
    const turn = ++revision;
    const choice = selected(key);
    const preset = PRESETS.find(item => item.id === choice);
    clearObjectURL();
    setBackground(preset ? preset.value : null, choice);
    if (choice !== 'custom') return;
    try {
      const blob = await fileOperation('wallpaper-page:' + key);
      if (turn !== revision) return;
      if (!(blob instanceof Blob)) {
        setBackground(null, 'inherit');
        return;
      }
      const url = URL.createObjectURL(blob);
      if (turn !== revision) { URL.revokeObjectURL(url); return; }
      activeObjectURL = url;
      setBackground('url("' + url + '")', 'custom');
    } catch (_) {
      if (turn === revision) setBackground(null, 'inherit');
    }
  }
  function choose(id) {
    if (id !== 'custom' && !PRESETS.some(item=>item.id===id)) return;
    settings[activeContext] = id;
    if (!saveSettings()) { inform('本机存储不可用，当前选择只在本次打开时有效。'); }
    void activate(activeContext);
    if (picker && picker.open) picker.close();
  }
  function inform(message) {
    if (pickerStatus) pickerStatus.textContent = message;
  }
  function refreshPicker() {
    if (!picker) return;
    picker.querySelector('#emoiWallpaperContext').textContent = contextName(activeContext);
    pickerGrid.replaceChildren();
    const current = selected(activeContext);
    for (const option of PRESETS) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'emoi-wall-option';
      button.setAttribute('aria-pressed', String(current === option.id));
      button.dataset.wall = option.id;
      const sample = document.createElement('span');
      sample.className = 'emoi-wall-option-sample';
      if (option.value) sample.style.backgroundImage = option.value;
      else sample.classList.add('emoi-wall-option-inherit');
      const title = document.createElement('strong');
      title.textContent = option.name;
      const desc = document.createElement('small');
      desc.textContent = option.caption;
      button.append(sample, title, desc);
      button.addEventListener('click', () => choose(option.id));
      pickerGrid.append(button);
    }
    inform('这张壁纸只用于当前页面；聊天记录、文件和记忆不会被修改。');
  }
  function openPicker() {
    if (!picker) return;
    refreshPicker();
    if (!picker.open) picker.showModal();
  }
  async function upload(file) {
    if (!file) return;
    if (!IMAGES.has(file.type) || file.size > MAX_BYTES || !file.size) {
      inform('请选择不超过 12 MB 的 JPEG、PNG、WebP、AVIF 或 HEIC 图片。');
      return;
    }
    const context = activeContext;
    if (uploadInput) uploadInput.disabled = true;
    inform('正在保存到本机…');
    try {
      await fileOperation('wallpaper-page:' + context, file, true);
      settings[context] = 'custom';
      saveSettings();
      // A slow photo write must not repaint a different page the user opened meanwhile.
      if (activeContext === context) await activate(context);
      if (picker?.open && activeContext === context) picker.close();
    } catch (error) {
      inform('保存失败：' + (error?.message || '请检查浏览器可用空间'));
    } finally {
      if (uploadInput) uploadInput.disabled = false;
    }
  }
  function createPicker() {
    picker = document.createElement('dialog');
    picker.id = 'emoiWallpaperDialog';
    picker.className = 'sheet emoi-wallpaper-picker';
    picker.setAttribute('aria-labelledby', 'emoiWallpaperHeading');
    const header = document.createElement('header');
    header.className = 'emoi-picker-head';
    const titleGroup = document.createElement('div');
    const kicker = document.createElement('span');
    kicker.className = 'emoi-picker-kicker';
    kicker.textContent = 'ÉMOI / AMBIENT ARCHIVE';
    const heading = document.createElement('h2');
    heading.id = 'emoiWallpaperHeading';
    heading.textContent = '为这个空间换一张风景';
    const caption = document.createElement('p');
    caption.id = 'emoiWallpaperContext';
    titleGroup.append(kicker,heading,caption);
    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'emoi-picker-close';
    close.textContent = '×';
    close.setAttribute('aria-label','关闭壁纸选择');
    close.addEventListener('click',()=>picker.close());
    header.append(titleGroup,close);
    pickerGrid = document.createElement('div');
    pickerGrid.className = 'emoi-wall-grid';
    const actions = document.createElement('div');
    actions.className = 'emoi-picker-actions';
    const uploadLabel = document.createElement('label');
    uploadLabel.className = 'emoi-wall-upload';
    uploadLabel.textContent = '＋ 上传当前页面壁纸';
    uploadInput = document.createElement('input');
    uploadInput.type = 'file';
    uploadInput.accept = 'image/jpeg,image/png,image/webp,image/avif,image/heic,image/heif';
    uploadInput.setAttribute('aria-label','上传当前页面壁纸');
    uploadInput.addEventListener('change',event=>{
      const file=event.target.files?.[0];
      event.target.value='';
      void upload(file);
    });
    uploadLabel.append(uploadInput);
    const reset = document.createElement('button');
    reset.type = 'button';
    reset.className = 'emoi-wall-reset';
    reset.textContent = '恢复此页默认';
    reset.addEventListener('click',()=>{
      delete settings[activeContext];
      saveSettings();
      void activate(activeContext);
      picker.close();
    });
    actions.append(uploadLabel,reset);
    pickerStatus = document.createElement('p');
    pickerStatus.className = 'emoi-picker-status';
    pickerStatus.setAttribute('role','status');
    const inner = document.createElement('div');
    inner.className = 'emoi-wallpaper-picker-body';
    inner.append(pickerGrid, actions, pickerStatus);
    picker.append(header, inner);
    document.body.append(picker);
    picker.addEventListener('click', event=>{
      if (event.target === picker) picker.close();
    });
  }
  function init() {
    createPicker();
    for (const id of ['chatWallpaperButton', 'pageWallpaperButton']) {
      const trigger = document.getElementById(id);
      if (trigger) trigger.addEventListener('click', openPicker);
    }
    const workspace = document.getElementById('workspaceDialog');
    if (workspace) workspace.addEventListener('close',()=>void activate(lastChat));
    void activate(activeContext);
  }

  window.EmoiWallpapers = { activate, open: openPicker, selected: () => selected(activeContext) };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded',init);
  else init();
})();
