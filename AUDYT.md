# Frap Grab validation

## 2.1.0

Renamed the application, executable, installer and update repository to Frap Grab.
Added a game selector to first-run setup and Settings. War Dogs is the only
currently supported profile. Capture process matching uses the selected profile.
Existing preferences and legacy voice-track tags remain supported.
81 unit tests passed. Historical validation notes follow.

# Audyt AutoClip 2.0 — aktualizacja 31.10.2026

## Aktualizacja 2.0.5 — pierwszy start i publiczna paczka

Pierwsze uruchomienie nowego profilu pokazuje czterokrokowy konfigurator w PL/EN.
Puste pole nicku jest jawnie wymagane dla automatycznych eliminacji/asyst; bez
nicku można wybrać ręczny zapis F8 i reakcje głosowe. Ta sama informacja i status
są na pulpicie. Brak nicku nie blokuje bufora, F8 ani mikrofonu, ale detektor
graficzny nie uruchamia wtedy identyfikacji gracza ani kalibracji.

Konfigurator zapisuje język, tryby detekcji, ekran, długość powtórki, folder i audio.
Nowy nick usuwa powiązanie z poprzednim prywatnym wzorcem. Po ukończeniu nie powraca
przy kolejnym starcie; istniejące skonfigurowane profile są migrowane bez resetu.
Przycisk w Ustawieniach pozwala otworzyć panel ponownie. Testy interfejsu sprawdzają
automatyczne otwarcie, walidację, oba warianty z nickiem/bez nicku i brak powtórzenia.

W starej dokumentacji paczki znaleziono prywatny nick z testów. Usunięto go również
z publicznych fixture testowych. Domyślna konfiguracja już wcześniej miała puste
nick i wzorzec, a prywatne pliki pozostają poza katalogiem dystrybucji.
Nowy audyt sprawdza skompilowane moduły EXE, zasoby/dokumenty, brak plików profilu
i brak kopii prywatnego PNG wzorca. Test wykrył stary wpis w paczce 2.0.4;
build 2.0.5 jest blokowany, jeśli audyt znajdzie taki wpis ponownie.

W panelu głównym i konfiguratorze jest właściwa ikona PNG zgodna z ikoną EXE/ICO,
zamiast litery zastępczej. Natywny pasek okna dostaje ciemny tryb DWM po utworzeniu
i mapowaniu, z prawidłowo typowanym uchwytem HWND. Zrzuty pokazują całą ramkę Windows,
w tym ciemny pasek i ikonę. Stan DWM potwierdza aktywny ciemny tryb.

75 testów: dodatkowo czysty profil, migracja, opcjonalny nick w trybie ręcznym,
walidacja i zachowanie poprzednich ustawień przy błędzie atomowego zapisu.

## Aktualizacja 2.0.4 — GPU, HUD, pulpit, język i aktualizacje

Profile rodzin kart są w publicznym JSON, ze źródłami NVIDIA/AMD. Krótki test
rzeczywistego kodowania i pełnego dekodowania zastępuje wcześniejsze uznawanie
samej obecności kodeka w FFmpeg za obsługę GPU. RTX 30 bez AV1, Navi24 bez
enkodera, fallback po błędzie sterownika, dedykowana karta przed integrą.
Domyślnie automat wybiera kodek/FPS/jakość, dla 4K wyższy bitrate; ręczny tryb
zostaje. Cache zależy od modelu, sterownika, FFmpeg i katalogu profili.

Na tym PC: wybrany RTX 5080 / AV1 / 60 FPS. Zintegrowany Radeon przeszedł H.264
i HEVC AMF; AV1 został poprawnie odrzucony. Test zapisu HEVC: DXGI-copy + WASAPI,
2560×1440/60, 3 ścieżki AAC stereo, pełne dekodowanie, zakończenie kodem 0.
Montaż na AMF przeszedł z D3D11VA przypisanym do urządzenia AMD (istotne w układzie
NVIDIA + AMD), CPU filtrami i sprzętowym HEVC, wraz z przenikaniami. RTX 5080
ponownie przeszedł zapis AV1 DXGI 60 FPS z 3 ścieżkami audio; stop około 0,41 s.
Brak fizycznych testów wydajności w grze na RX 7900 XTX/9070 XT/9060 XT i innych RTX.

Automatyczna geometria HUD nie rozciąga szerokości na ultrawide i centruje
powiadomienie asysty. Automatyczna kalibracja z pliku rozpoznała nick użytkownika
bez ręcznego prostokąta; wzorzec przetestowano na innym klipie, zgodność 0,956–0,994.
OCR kalibracji nie działa w aktywnej grze, a sam live-detektor nadal nie ładuje OCR.
Ręczne procenty i test OCR ukryto w Advanced. Jeśli rozpoznanie się nie powiedzie,
aplikacja nie udaje poprawnej kalibracji.
Wzorce skalowane są do natywnych pikseli, nie przez rozciąganie obrazu do starego
ROI. Przy innej wysokości wyświetlacza następny zapis może posłużyć do automatycznej
kalibracji natywnej. Test na rzeczywistym klipie przekodowanym do 1280×720:
automatyczne rozpoznanie bez ręcznego zaznaczania, zgodność nicku 0,970.
Test powiadomienia asysty na skalowanych klatkach: 1080p 0,836, 720p 1,000;
ujemne klatki odpowiednio 0,311 i 0,370. To testy algorytmu na skalowanych obrazach,
nie fizyczne testy innych monitorów czy wszystkich wariantów HUD-u.

Ręczna powtórka ma osobny wybór długości 30 s–30 min. Bufor rośnie bez restartu
i zaczyna gromadzić dłuższy zakres od zmiany. Manifest zwiększono do 2048 segmentów,
aby limit listy nie ucinał powtórek ponad ok. 8 minut. Skrót zapisuje wybraną długość,
nie zawsze cały bufor. Automatyczne wycinki zachowują dotychczasowe krótkie zakresy.

Usunięto marketingowy nagłówek, podtytuły stron i wordmark obok logo. Nazwa głównej
strony: Pulpit. Angielski działa bez restartu; wartości opcji pozostają stabilne,
więc tłumaczenie nie zmienia logiki filtrów, kolejności ani enkodera.

Updater: publiczne GitHub Releases, stabilne wersje, ścisłe dopasowanie instalatora,
repozytorium i digestu SHA-256, atomowe pobranie, odrzucenie uszkodzonego pliku.
Repozytorium jest puste, niczego nie opublikowano. Testy działają na fixture API;
pełny test aktualizacji z publicznego wydania wymaga przyszłej publikacji.

68 testów obejmuje dodatkowo rodzinę GPU i fallback, HUD różnych proporcji,
wybór długości, żywą zmianę PL/EN i niezmienność wartości opcji oraz aktualizator.
Końcowa kontrola biblioteki wykazała niezależny błąd CTk 6: `image=None` zostawiało
nieaktualny identyfikator obrazu w natywnej kontrolce Tk. Po garbage collection
odświeżenie tekstu miniatury rzucało `pyimage does not exist`. Warstwa etykiety
teraz czyści także natywny obraz; regresja jest objęta testem zwolnienia i podmiany.

## Aktualizacja 2.0.3 — asysta przy helikopterze, powtórki i wybór filmu

Przeanalizowano `Desktop/test2.mp4` i 9 źródeł z 30.10. W końcowym źródle
asysta jest około 43,6 s; poprzedni film ucinał źródło przy 42,625 s.
Komunikat „ASYSTA PRZY ZABÓJSTWIE” potwierdzono wizualnie. Wzorzec z tego HUD-u
jest osobnym, dwuklatkowym detektorem offline i live, bez OCR. Sam licznik
wpisów z własnym nickiem nie wykrywa asyst. Detekcja końcowej asysty: 43,875 s.

Eliminacja z klipu 17:39:36 jest też w powtórce mikrofonowej 17:40:00.
Wyrównanie obrazu: przesunięcie 10 s, 17 zgodnych ruchomych próbek; 7 s
powtórzonego materiału usunięte przez sumę zakresów na wspólnej osi czasu.
Nowe nagrania zapisują identyfikator sesji i rzeczywisty początek segmentu.
Nie polegamy wyłącznie na datach eksportu ani pojedynczej podobnej klatce.

Poprawiony `Desktop/test2_poprawiony.mp4`: 104,41 s, 9 ujęć, NVDEC/CUDA/NVENC.
Pełne dekodowanie bez błędów i wizualna kontrola końca: asysta widoczna.
Cały eksport z istniejącej analizy około 36,6 s. Źródła i poprzedni film zachowane.
Sam zapis źródłowy kończy się w trakcie dalszego ostrzału; nie da się odzyskać
materiału po jego końcu. Nowa asysta na żywo przedłuży zapis o czas po zdarzeniu.
Dodatkowo kolejne zdarzenie nie może już skrócić oczekiwania po reakcji głosowej.

Wspólny planner dla podglądu długości i eksportu: filtry eliminacji, asyst,
reakcji, asysty w odległości do 8/15 s od eliminacji, również między źródłami.
Na tych samych 9 źródłach: wszystkie 104,36 s, eliminacje 53,44 s, eliminacje
i asysty do 8 s bez głosów 61,54 s. Przenikania uwzględnione w szacowaniu.
Zmiana filtrów unieważnia widoczny plan; rzeczywisty czas jest pokazany po eksporcie.

Dodawanie muzyki po montażu kopiuje obraz (`-c:v copy`) i zapisuje nowy plik.
Test integracyjny potwierdza identyczność SHA-256 każdego pakietu wideo przed
i po dodaniu podkładu oraz poprawne pełne dekodowanie. Głośność jest regulowana.
49 testów jednostkowych obejmuje m.in. koniec z asystą, scalenie powtórek,
statyczne fałszywe podobieństwo, most między grupami, filtry i wspólny czas asyst.
Przetestowano również interfejs: wybór samych eliminacji, podgląd 0:53,
rzeczywisty eksport 53,48 s i dodanie podkładu do gotowego wyniku. Kontrolki
odblokowują się po pracy, czas i gotowy plik są widoczne. Osobny test potwierdza
dodawanie muzyki również do niemego filmu.

## Aktualizacja 2.0.2 — wszystkie wykryte akcje i rozmowy

Dwie pominięte eliminacje są w drugim źródle około 41–44 s. Cięcie 46–54 s
w 2.0.1 je pomijało. Tymczasowy montaż całych klipów został odrzucony jako zbyt
rozwlekły; nie jest domyślny w wydaniu 2.0.2.

Domyślny automat skanuje źródła jednym przebiegiem NVDEC, analizując mały obszar
killfeedu przy 4 Hz, bez OCR w ścieżce graficznej. Uwzględnia każde rozpoznane
zdarzenie i wszystkie zapisane znaczniki. Reakcje głosowe analizuje osobno,
a bliskie okna z kontekstem łączy w jedną scenę. Buforuje rozpoznanie i strumieniuje
próbki, aby nie trzymać całego materiału w pamięci. Niepewne źródła są wymienione
w raporcie i komunikacie, nie zapełniają filmu losowym ruchem kamery.

Weryfikacja na źródłach użytkownika: eliminacje przy 41,125 i 43,375 s,
zgodność wzorca 0,996 i 0,995. Plan 37,625–46,875 s zawiera obie oraz premię po
ich wykonaniu. Wynik `Videos/WarDogsClips/test_najlepsze_akcje_poprawione.mp4`:
9,27 s, 1080p/60, pełne dekodowanie bez błędów. Pierwsze rozpoznanie dwóch źródeł
z eksportem: około 17,6 s; kolejne korzystają z pamięci podręcznej.

Pierwszy historyczny klip mikrofonowy nie ma audio ani wykrytych eliminacji.
Został jawnie zgłoszony jako nierozpoznany; dawnych rozmów nie da się odzyskać.
Raw źródła pozostały nienaruszone. Samo przejście testu dekodowania nie oznacza,
że montaż trafnie wybrał sceny — dlatego zakresy sprawdzono względem obu zdarzeń.

Nowe nagrania mają miks Gaming + mikrofon + Sonar Chat oraz osobne ścieżki głosów.
Dzięki temu głośne strzały nie muszą służyć jako wskaźnik rozmowy. Głośna reakcja
może odświeżać znacznik co 3 s; zapis ma zakres 20 s przed/15 s po w granicach bufora.
Każdy znacznik zachowuje swój typ, także przy łączeniu eliminacji z reakcją.
Test rzeczywistych wejść: AV1 2560×1440/60, trzy ścieżki AAC stereo 48 kHz,
pełne dekodowanie wszystkich strumieni, poprawne zakończenie FFmpeg (kod 0),
zatrzymanie około 0,34 s. Audio idzie lokalnie przez 127.0.0.1, a stdin służy
sterowaniu i domykaniu segmentu. Etykiety ścieżek sprawdzono w kontenerze MP4.

Regresje: 35 testów, w tym obie konkretne eliminacje, każde odległe zdarzenie,
brak losowego filmu przy nierozpoznanym źródle, głośna aktywność i brak uznawania
stałego poziomu audio za cały film, typy znaczników, źródła głosów oraz anulowanie.
Nie obiecujemy rozpoznania każdego dowcipu ani zapisania zdarzenia, którego
nie ma w materiale. Nowy automat nie ukrywa braku rozpoznania.

## Aktualizacja 2.0.1 — czas montażu

Starsza wersja analizowała importowane/legacy klipy przez około 90 osobnych
wywołań `VideoCapture.set`, co wielokrotnie dekodowało te same grupy klatek AV1
na CPU. NVENC nie pracował w tym etapie. Zastąpiono to jednym przebiegiem FFmpeg:
NVDEC → wybór próbek → CUDA 160×90 → małe klatki do heurystyki. Wyniki są buforowane.
Starsze pliki z nazwą zdarzenia wykorzystują końcówkę, bez ponownego skanowania.
Przygotowanie ujęć 16:9 odbywa się w NVDEC/CUDA/NVENC, a wejścia do przenikań
również są dekodowane przez NVDEC. Przenikanie pozostaje filtrem CPU.

Test na dokładnie dwóch plikach z `test.mp4.edit.json` użytkownika: 7,2 s na
film około 15,78 s, AV1/1080p/60, z przejściem i pełnym dekodowaniem wyniku bez błędów.
Pierwszy test pełnej analizy dwóch innych rzeczywistych klipów: około 17 s.
Nie jest to gwarancja takiego czasu dla dowolnej długości, formatu lub liczby plików.
Dodano postęp podczas analizy, anulowanie własnego zadania i powiązanie miniatur
z właściwym interpreterem Tk. Regresje: 21 testów, w tym analiza pojedynczym
przebiegiem, cache, pierwszeństwo znaczników i przerwanie procesu.

FFmpeg/NVENC jest sensowną podstawą samodzielnego rejestratora. Problemy poprzedniej
wersji wynikały przede wszystkim z implementacji bufora, wykrywania i eksportu.

| Usterka | Naprawa |
|---|---|
| Brak wejścia audio; nieme klipy | WASAPI, natywny format Sonar 8 kanałów/96 kHz, AAC stereo |
| Odczyt plików w trakcie zapisu i wyścig z nadpisaniem | Niepowtarzalne segmenty, indeks zamkniętych plików, migawka eksportu |
| Zakres przez liczbę plików zamiast czasu | Czas segmentów z indeksu CSV |
| Ciche odrzucanie kolejnego eksportu | Kolejkowanie i łączenie bliskich akcji |
| Wspólny katalog bufora wielu uruchomień | Katalog sesji, blokada instancji, kontrola zakresu sprzątania |
| Launcher uznawany za grę | Oddzielenie procesu i aktywnego okna gry |
| Status aktywny mimo awarii FFmpeg | Potwierdzenie segmentem, jawny błąd, jedna próba GDI |
| Detektor mógł badać drugi monitor | Wspólne mapowanie rzeczywistych wyjść DXGI |
| „Pure Pixel Probe” faktycznie wywoływał RapidOCR | Domyślny detektor wzorca bez OCR/modelu, OCR tylko jako opcja |
| Nietypowane 64-bitowe uchwyty GDI | Poprawne typy uchwytów; odczyt DXGI preferowany nad GDI |
| Blokada wszystkich eliminacji na 8 sekund | Deduplikacja wpisów, bez globalnej blokady akcji |
| Ratunek zgadywany po zniknięciu napisu | Usunięto niepotwierdzone rozpoznawanie |
| Nick dopasowany przez podciąg | W OCR pełny token, tag klanu i typowe pomyłki znaków |
| Jakość bitrate ignorowana, błędne presety CPU/AMD/Intel | Wspólne opcje odpowiednie dla enkodera |
| Zmiana skrótu bez ponownej rejestracji | Ponowna rejestracja po zastosowaniu ustawień |
| Skaner i GUI miały różny schemat zdarzeń | Wspólny parser i schemat z victim/raw_text |
| Montaż zawsze brał końcówkę pliku | Znaczniki faktycznych akcji, heurystyka ruchu dla importu |
| Muzyka wywracała pliki bez audio | Cisza i normalizacja wszystkich ujęć |
| Różne rozmiary/fps powodowały błędy łączenia | Normalizacja 1080p/60, stereo/48 kHz |
| Sukces na podstawie samego istnienia MP4 | Kod wyjścia, FFprobe, atomowy plik wynikowy |
| Tk obsługiwany z wątków roboczych | Kolejka zdarzeń i UI wyłącznie w wątku Tk |
| Miniatury blokowały ekran / nieograniczona równoległość | Osobna pula 2 wątków, stronicowanie i filtr daty |
| Duże/dynamiczne listy powodowały czarne kontrolki Tk w Windows | Pula 10 stałych wierszy, paginacja i sprawdzenie również w EXE |
| Jednoczesne dekodowanie całego dnia przy przenikaniach | Łączenie w grupach do 8 wejść, sprzątanie części po połączeniu |
| Ścieżki konkretnego komputera w buildzie | Względny build, lokalne narzędzia i przenośna dystrybucja |
| Fałszywe obietnice „0% CPU/FPS”, przeładowane UI | Nowy interfejs i opis rzeczywistych możliwości |

## Sprawdzone

- 17 testów regresji: parser, nick/klan, kilka akcji, słabe rozpoznania, segmenty,
  pusty bufor, presety, bitrate, apostrof w ścieżce, uszkodzone preferencje,
  dopasowanie graficzne, brak ciągłych powtórek, wymagana ponowna kalibracja
  i test potwierdzający, że działająca ścieżka graficzna nie inicjalizuje OCR.
- Prawdziwe nagranie DXGI/H.264 NVENC: 2560×1440/60, AAC stereo/48 kHz, około 7 s.
  Klatka przedstawia grę; audio ma niezerowy sygnał. Pełne dekodowanie bez błędów.
- Prawdziwe nagranie DXGI/AV1 NVENC (kodek z dotychczasowej konfiguracji): te same
  parametry obrazu/audio, około 7 s, pełne dekodowanie bez błędów.
- Powtórzony test AV1 podczas równoczesnej pracy graficznego detektora DXGI:
  poprawny plik obrazu/audio i brak zainicjalizowanego OCR.
- OCR offline prawdziwego killfeedu: dwa wiersze, prawidłowy napastnik i brak
  przypisania cudzej eliminacji do nieobecnego w nim nicku użytkownika.
- Prywatny wzorzec nicku użytkownika przygotowany jednorazowo z rzeczywistego starego klipu
  z dwiema eliminacjami. 5 pobliskich klatek: po 2 poprawne dopasowania, wynik
  korelacji około 0,994–1,000. 7 klatek bez własnej eliminacji: 0 dopasowań,
  maksymalna korelacja około 0,288–0,336. Wzorzec zapisany w konfiguracji.
- Krótki pomiar odczytu obszaru i dopasowania na tym komputerze: 20 próbek GDI
  miało medianę 9,14 ms, p95 11,86 ms; 20 próbek DXGI medianę 4,20 ms,
  p95 7,81 ms. To czas odczytu i analizy, nie pomiar frametime gry, nie gwarancja
  stałych wartości i nie obietnica „0% spadku FPS”. Próbkowanie: około 4 Hz.
- Eksport mieszanych klipów 640×360/30 FPS z audio + 480×360/24 FPS bez audio:
  YouTube 1920×1080/60 z przenikaniem; Shorts 1080×1920/60 z tłem;
  montaż z muzyką; przycinanie kodekiem CPU. Wszystkie pliki zdekodowane w całości.
- Montaż 9 ujęć sprawdza przejście przez dwa poziomy łączenia w grupach;
  gotowy film około 5,63 s również w pełni zdekodowany bez błędów.
- Test pięciu ekranów GUI, generowanie podglądów do kontroli wyglądu.
- Test na istniejących 111 klipach: wybór klipu, zaznaczenie wszystkich 27 plików
  wybranego dnia, następna strona i przeniesienie wyboru do studia.
- Diagnostyka dystrybucji obejmuje modele offline OCR, WASAPI, monitory, detektor
  DXGI oraz lokalne FFmpeg/FFprobe. Surowe raporty: `scratch/verification`.

## Pozostaje do dłuższego sprawdzenia

Nie wykonano wielogodzinnego nagrywania, pomiaru FPS/frametime ani precision/recall
na oznaczonym zbiorze własnych meczów. Krótkie testy nie dowodzą wykrywania każdej
akcji ani braku dryfu audio podczas długiej sesji. Nie testowano AMF, QSV, HDR ani
wszystkich trybów pełnego ekranu. Montaż sprawdzono na krótkich plikach o różnych
parametrach; nie na stu wejściach lub wielogodzinnym filmie.

Detektor graficzny wymaga stabilnego HUD-u; nie rozumie gry. Przy zastąpieniu wpisów
w killfeedzie bez zmiany liczby własnych widocznych wpisów może nie wykryć następnej
akcji. Celem jest zachowanie fragmentu walki, a F8 pozostaje niezależnym zapisem.
Heurystyka ruchu w importowanych plikach także nie rozumie semantyki meczu.

## Źródła techniczne

- [NVIDIA — FFmpeg/NVENC](https://docs.nvidia.com/video-technologies/video-codec-sdk/13.0/pdf/Using_FFmpeg_with_NVIDIA_GPU_Hardware_Acceleration.pdf)
- [FFmpeg — segmenty](https://ffmpeg.org/ffmpeg-formats.html)
- [FFmpeg — ddagrab](https://www.ffmpeg.org/ffmpeg-filters.html)
- [PyAudioWPatch — WASAPI](https://github.com/s0d3s/PyAudioWPatch)
- [DXcam — region-aware Desktop Duplication](https://github.com/ra1nty/DXcam)
- [Windows Graphics Capture — rozważona alternatywa](https://learn.microsoft.com/en-us/windows/apps/develop/media-authoring-processing/screen-capture)

OBS jako zewnętrzny silnik nie został wdrożony. Aplikacja działa samodzielnie.

## Dodatkowy test ścieżek głosów

Syntetyczny test miał głośną grę w 1–3 i 4–5 s oraz głos tylko w osobnej ścieżce w 7–8 s. Analiza wybrała wyłącznie 7–8 s. Etykiety handler_name mikrofonu i Sonar Chat sprawdzono w MP4.
