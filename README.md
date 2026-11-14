# slicing

**Для следующей ИИ:** начните с [docs/START_HERE.md](docs/START_HERE.md), [актуального состояния](docs/CURRENT_STATE.md) и [истории решений](docs/HISTORY.md). Здесь сохранены код и выборочный текстовый контекст проекта; тяжёлые локальные данные исключены из Git.

Текущий рабочий процесс использует HQ 1920×1080 и экспорт 1080×1920. Описанный ниже первоначальный загрузчик предпочитает 480p; для существующих HQ-планов используется отдельный рабочий корень. Последнее исправление монолога — **BATCH_18b_v2**, его путь пока не перенесён в исходный batch-индекс.

Штатный запуск в терминале VS Code подготавливает один публичный архив `evelone2004` и сохраняет его расшифровку. При новом выборе берётся самый ранний доступный VOD с 11 июля 2026 года по Москве, который ещё нужно подготовить. Скачанный VOD без расшифровки возобновляется первым, даже если запись уже исчезла из Twitch. Для монтажа используется отдельный запуск с JSON-планом.

### Первый запуск на Windows 11

Нужны Python 3.11, PostgreSQL и FFmpeg с `libass`, `libx264` и AAC. Распакуйте ZIP и укажите путь к `ffmpeg.exe`, рядом с которым находится `ffprobe.exe`. Подходящая сборка — [FFmpeg Essentials Build](https://www.gyan.dev/ffmpeg/builds/).

На этой машине PostgreSQL 18 принимает соединения на порту **55432**. Если PostgreSQL ещё нет, выберите компонент PostgreSQL Server в мастере установки и запомните порт. Обычно это 5432. [Установщик PostgreSQL для Windows](https://www.postgresql.org/download/windows/)

В PowerShell из корня проекта выполните один раз. Подставьте порт своего сервера и существующую локальную роль с правом `CREATEDB`.

```powershell
$slicingPython = "$env:LOCALAPPDATA\slicing\venv\Scripts\python.exe"
if (!(Test-Path -LiteralPath $slicingPython)) {
    py -3.11 -m venv "$env:LOCALAPPDATA\slicing\venv"
    & $slicingPython -m pip install -e .
}

$slicingPort = 55432
& 'C:\Program Files\PostgreSQL\18\bin\createdb.exe' -h 127.0.0.1 -p $slicingPort -U postgres -W slicing
```

Для запуска откройте терминал VS Code в корне проекта и задайте подключение в этом терминале. Пароль вводится в защищённом запросе PowerShell.

```powershell
$slicingPython = "$env:LOCALAPPDATA\slicing\venv\Scripts\python.exe"
$slicingPort = 55432
$env:SLICING_FFMPEG = "$env:LOCALAPPDATA\slicing\ffmpeg\ffmpeg-9.0.2-essentials_build\bin\ffmpeg.exe"
$slicingCredential = Get-Credential -UserName postgres -Message 'Локальная база slicing'
$slicingUser = [uri]::EscapeDataString($slicingCredential.UserName)
$slicingPassword = [uri]::EscapeDataString($slicingCredential.GetNetworkCredential().Password)
$env:SLICING_DATABASE_URL = "postgresql://${slicingUser}:${slicingPassword}@127.0.0.1:${slicingPort}/slicing"
Remove-Variable slicingCredential, slicingPassword
& $slicingPython -m slicing
```

При настроенном `pgpass.conf` можно задать `SLICING_DATABASE_URL` в виде `postgresql://postgres@127.0.0.1:55432/slicing`. Если FFmpeg доступен в `PATH`, пропустите присвоение `SLICING_FFMPEG`.

Переменная подключения действует до закрытия терминала. Приложение повторяемо создаёт таблицу `public.vods` с полями `twitch_id` (первичный ключ), `published_at`, `local_path` и `status`.

- `downloaded` фиксирует проверенный исходник. При сбое распознавания следующий запуск использует этот файл.
- Исторические записи со статусами `processed` и `no_moments` исключаются из новой подготовки.

Если выбранный исходник уже лежит в `data/vods/`, приложение проверит его и зарегистрирует в БД. Whisper base распознаёт русскую речь на CPU. Если весов модели ещё нет, они скачиваются при первом распознавании. JSON в `data/review/transcript_<id>.json` содержит ID VOD, длительность исходника в секундах и реплики с полями `start`, `end` и `text`. Готовая расшифровка считается завершением подготовки. Следующий запуск пропускает её при выборе VOD. Для экономии места при загрузке предпочтительна версия VOD до 480p.

### Монтаж по плану

В Codex вызовите `$slicing-editor` вручную и передайте ID VOD, интервал и ID клипа. Редактор сохраняет список самостоятельных эпизодов до просмотра прежних ответов моделей, затем проверяет исходные кадры и готовит план для одного эпизода. Список пилота для 01:07:50–01:10:24 находится в `data/review/codex_pilot/candidates_2876630043.json`.

Для рендера CX01 запустите из корня проекта тот же Python с настроенным FFmpeg.

```powershell
& $slicingPython -m slicing --edit-plan data/review/edit_plan_2876630043.json --clip CX01
```

В плане версии 1 укажите локальный файл `data/vods/<id>.mp4` в `source.file`, ID записи в `source.vod_id` и массив отрезков `start_ms`, `end_ms` у нужного клипа в `clips`. Отрезки склеиваются в порядке массива. Границы сверяются с длительностью файла по FFprobe. Этот режим работает с локальным исходником без подключения к PostgreSQL.

В этой же версии доступны необязательные поля композиции и субтитров.

- `header` у клипа задаёт строку `label` и одну или две строки `lines` для верхней плашки.
- `framing` у отрезка задаёт `name` и список `panels`. Каждая панель описывает прямоугольники `crop` в исходнике и `place` на холсте 720 × 1280. Формат обоих массивов `[x, y, ширина, высота]` с целыми неотрицательными координатами и положительными чётными размерами. Начало `crop` также должно иметь чётные координаты. Если поле пропущено, рендер вписывает весь исходный кадр.
- `captions` у отрезка содержит реплики с `start_ms` и `end_ms` в шкале исходника и одной или двумя строками `lines`. При ручной разметке укажите `captions` у каждого отрезка. Для паузы используйте пустой список.
- Без `captions` Whisper распознаёт склеенный звук, а ASS выделяет активное слово. `subtitle_spelling.replacements` позволяет уточнить написание слова, а `first_segment_joins` объединяет пары слов первого отрезка. Ключи записываются строчными буквами.

Рендер сохраняет MP4, ASS и манифест с исходными и выходными интервалами в `data/review/mvp/<id>/<clip>/`. План содержит три композиции A21 для вопроса, выбора и реакции. Для его сборки укажите `--clip A21`. Для повторного рендера перенесите предыдущий результат.

По умолчанию используется исходный звук. Для локальной инструментальной дорожки добавьте `--music` с путём к файлу. Громкость дорожки понижается во время речи, в конце она плавно затихает.

### Вычитка титров по меткам

Для новой версии CX01 предусмотрен отдельный план `data/review/codex_pilot/subtitles/edit_plan_CX01_subtitles.json`. Поле `subtitle_review` содержит имена файлов `draft` и `edits` рядом с планом. Оно используется вместо `captions` и `subtitle_spelling`.

Один раз подготовьте черновик из склеенного звука с установленным локальным Whisper.

```powershell
$slicingPlan = 'data/review/codex_pilot/subtitles/edit_plan_CX01_subtitles.json'
& $slicingPython -m slicing --edit-plan $slicingPlan --clip CX01_subtitles --draft-subtitles
```

В черновике каждому слову назначен `id` и номер отрезка `segment`. `start_ms` и `end_ms` отсчитываются от начала клипа. В JSON правок Sol сохраняет `schema_version` со значением `1`, `draft_sha256` и список `edits`. У правки есть `word_ids` и `text`. Указывайте соседние ID одного отрезка в порядке черновика. Пустой `text` удаляет распознанный шум. При замене одного слова активная подсветка использует исходный интервал. При слиянии или разбиении весь исправленный текст отображается одной фразой на интервале исходных ID.

Соберите клип с готовыми файлами черновика и правок. Рендер сверяет SHA-256 и границы отрезков и использует сохранённые метки при каждой сборке.

```powershell
& $slicingPython -m slicing --edit-plan $slicingPlan --clip CX01_subtitles
```

### Проверки

```powershell
& $slicingPython -m slicing --list-vods
& $slicingPython -m unittest discover -s tests -v
```

Для проверки PostgreSQL и FFmpeg укажите `SLICING_TEST_DATABASE_URL` для отдельной пустой базы `slicing_test` и ту же сборку FFmpeg. Тест моделирует сбой распознавания на сгенерированном исходнике, затем проверяет повторное использование этого файла, запись JSON и переход к следующему VOD.
