/* Service Worker：只缓存「壳」，不缓存任何接口数据。
 *
 * 目的很单纯：装到主屏后，即使电脑那边短暂连不上，点开也能看到界面并给出提示，
 * 而不是一片白屏。
 *
 * 两条原则：
 * 1. 接口请求（/chat、/upload 等）一律不碰，直接走网络；
 * 2. 页面导航走「网络优先」，拿到新版本就更新缓存，断网时回落到缓存。
 */

const CACHE = 'character-chat-v1';

const SHELL = [
    '/',
    '/manifest.webmanifest',
    '/icons/icon-192.png',
    '/icons/icon-512.png',
    '/icons/apple-touch-icon.png',
];

// 这些路径是接口，绝不能缓存
const API_PREFIXES = [
    '/chat', '/upload', '/characters', '/chapters', '/persona', '/personas',
    '/session', '/memory', '/documents', '/health',
];

self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE)
            .then((cache) => cache.addAll(SHELL))
            .then(() => self.skipWaiting())
            .catch(() => self.skipWaiting())
    );
});

self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys()
            .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
            .then(() => self.clients.claim())
    );
});

self.addEventListener('fetch', (event) => {
    const request = event.request;

    // 只处理 GET
    if (request.method !== 'GET') return;

    const url = new URL(request.url);

    // 跨域（比如把接口指到别的服务器）一律不管
    if (url.origin !== self.location.origin) return;

    // 接口请求不缓存
    if (API_PREFIXES.some((p) => url.pathname.startsWith(p))) return;

    // 页面导航：网络优先，失败回落到缓存的首页
    if (request.mode === 'navigate') {
        event.respondWith(
            fetch(request)
                .then((response) => {
                    const copy = response.clone();
                    caches.open(CACHE).then((cache) => cache.put('/', copy)).catch(() => {});
                    return response;
                })
                .catch(() => caches.match('/').then((hit) => hit || Response.error()))
        );
        return;
    }

    // 静态资源：缓存优先
    event.respondWith(
        caches.match(request).then((hit) => hit || fetch(request).then((response) => {
            const copy = response.clone();
            caches.open(CACHE).then((cache) => cache.put(request, copy)).catch(() => {});
            return response;
        }))
    );
});
