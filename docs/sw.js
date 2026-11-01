/* Service Worker：只缓存界面外壳。数据和接口一律走网络。
 *
 * 纯前端版本的"接口"是第三方大模型服务器，跨域请求不归这里管。
 */

const CACHE = 'character-chat-lite-v1';

const SHELL = [
    './',
    './index.html',
    './manifest.webmanifest',
    './icons/icon-192.png',
    './icons/icon-512.png',
    './icons/apple-touch-icon.png',
];

self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE)
            .then((cache) => cache.addAll(SHELL))
            .catch(() => {})
            .then(() => self.skipWaiting())
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
    if (request.method !== 'GET') return;

    const url = new URL(request.url);
    // 只处理本站资源，第三方接口不碰
    if (url.origin !== self.location.origin) return;

    if (request.mode === 'navigate') {
        event.respondWith(
            fetch(request)
                .then((res) => {
                    const copy = res.clone();
                    caches.open(CACHE).then((c) => c.put('./index.html', copy)).catch(() => {});
                    return res;
                })
                .catch(() => caches.match('./index.html').then((hit) => hit || Response.error()))
        );
        return;
    }

    event.respondWith(
        caches.match(request).then((hit) => hit || fetch(request).then((res) => {
            const copy = res.clone();
            caches.open(CACHE).then((c) => c.put(request, copy)).catch(() => {});
            return res;
        }))
    );
});
