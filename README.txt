BORINGTUBE V2

Что изменилось:
- YouTube iframe больше не используется.
- yt-dlp получает один готовый поток, в котором уже есть видео + звук.
- Backend НЕ сохраняет ролик на диск.
- Он только проксирует поток в обычный HTML5 <video>.
- В интерфейсе больше нет элементов YouTube.

СТРУКТУРА

frontend/
  index.html
  manifest.webmanifest
  sw.js

backend/
  app.py
  requirements.txt
  Dockerfile
  .dockerignore

КАК ЭТО РАБОТАЕТ

Телефон
  ↓
GitHub Pages
  ↓
POST /api/resolve
  ↓
yt-dlp получает актуальный A/V stream
  ↓
/stream/<token> проксирует байты
  ↓
обычный HTML5 video player

ПОЧЕМУ BACKEND ПРОКСИРУЕТ ВИДЕО

Нельзя надёжно просто передать телефону временную googlevideo-ссылку,
которую yt-dlp получил на сервере: такие URL временные и могут зависеть от
сетевой сессии/IP.

Поэтому backend сам получает видеобайты и сразу пересылает их браузеру.
Файл на диск при этом не создаётся.

ПЕРЕД ПУБЛИКАЦИЕЙ

В frontend/index.html найди:

const BACKEND = "https://PASTE-YOUR-BACKEND-HERE";

и замени на адрес своего backend, например:

const BACKEND = "https://boringtube-backend.onrender.com";

BACKEND

Dockerfile уже:
- устанавливает Python;
- устанавливает Deno;
- ставит yt-dlp[default];
- запускает Flask через gunicorn.

Для полного YouTube support yt-dlp сейчас использует внешний JavaScript runtime;
здесь им служит Deno.

ПЕРЕМЕННАЯ ОКРУЖЕНИЯ

ALLOWED_ORIGIN

Для теста можно не задавать.
Для публичного backend лучше указать origin своего GitHub Pages, например:

https://username.github.io

Это разрешит API-вызовы только с твоего сайта на уровне браузерного CORS.

ОГРАНИЧЕНИЕ КАЧЕСТВА

Эта версия намеренно выбирает один уже готовый поток:
video + audio.

Это делает систему очень простой и не требует FFmpeg, но у некоторых видео
максимальное качество такого совмещённого потока может быть ниже, чем 1080p/4K.

Это сознательный компромисс BoringTube v2.
