# Kavram rehberi

Bu proje birkaç altyapı kavramını küçük ama gerçek bir örnekte bir araya getiriyor. Her bölüm aynı sırayı izliyor:
- kavram ne,
- projede nerede,
- neden öyle yapıldı,
- elle ne deneyebilirsin.

Okuma sırası önerisi: REST → Kuyruk/Worker → Docker → Compose → Kubernetes → CI.

---

## 1. REST API ve asenkron işler

**Ne:** Kaynaklar (burada `datasets`) URL'lerle temsil edilir, HTTP metotları da işlemi söyler:
- `POST` oluşturur,
- `GET` okur,
- `DELETE` siler.

**Projede:** [`datadigest/api/routes_datasets.py`](../datadigest/api/routes_datasets.py)

**Neden 202 Accepted?** Analiz saniyeler sürebilir. API dosyayı kaydeder ve hemen "aldım, işleyeceğim" der (202). İstemci sonra `GET /api/datasets/{id}` ile durumu yoklar (polling). Böylece büyük bir dosya, HTTP isteğini dakikalarca açık tutmaz.

**Durum kodları:**

| Kod | Ne zaman |
|---|---|
| 202 | Kabul edildi |
| 400 | Boş dosya |
| 404 | Yok |
| 409 | Henüz hazır değil |
| 413 | Çok büyük |
| 415 | Yanlış dosya tipi |
| 422 | Geçersiz UUID (FastAPI otomatik verir) |

**Dene:** `http://localhost:8000/docs` adresinde Swagger arayüzünden dosya yükle. Dönen `id` ile `GET` isteğini tekrarla.

---

## 2. Kuyruk ve worker

**Ne:** API işi kendisi yapmak yerine bir kuyruğa "şu veri setini işle" notu bırakır. Ayrı çalışan worker süreçleri bu notları alıp işler.

**Projede:**
- [`jobqueue.py`](../datadigest/jobqueue.py): Redis listesi. `LPUSH` ile sola eklenir, `BRPOP` ile sağdan alınır, yani FIFO.
- [`worker.py`](../datadigest/worker.py): Sonsuz döngü, her turda bir iş.
- [`jobs.py`](../datadigest/jobs.py): Asıl iş (oku, analiz et, kaydet).

**Neden:**
- API hızlı kalır.
- Analiz CPU yiyen bir iş. Worker sayısını API'den bağımsız artırabilirsin.
- `BRPOP` atomiktir: aynı iş iki worker'a gitmez.

**SIGTERM:** Kubernetes bir pod'u kapatırken önce SIGTERM gönderir, `terminationGracePeriodSeconds` kadar bekler, sonra öldürür. Worker sinyali yakalayıp elindeki işi bitirir, sonra çıkar. Bunun için [`Worker.stop`](../datadigest/worker.py)'a bak.

**Worker çökerse ne olur? Güvenilir kuyruk.** İlk sürümde `BRPOP` kullanılıyordu: iş kuyruktan çıkar çıkmaz worker'ındı. Worker ölürse iş de giderdi. Şimdiki tasarım ([`jobqueue.py`](../datadigest/jobqueue.py)) şöyle:
1. Worker işi `BLMOVE` ile **atomik olarak** kuyruktan `processing` listesine taşır. İş hiçbir an iki listenin dışında değildir.
2. İş bitince worker onaylar (**ack**) ve iş listeden silinir.
3. Worker onaylamadan ölürse iş `processing`'de kalır. Her worker periyodik olarak **görünürlük zaman aşımını** (`JOB_VISIBILITY_SECONDS`) aşan işleri kuyruğa geri koyar.
4. `MAX_JOB_ATTEMPTS` denemeden sonra iş **ölü mektup (dead-letter)** listesine gider ve veri seti "failed" olur.

Bu garantinin adı **at-least-once** (en az bir kez): bir iş iki kez çalışabilir. Bu yüzden işleyiciler **idempotent** olmak zorunda, yani iki kez çalışınca sonuç değişmemeli. Bizimkiler öyle: tekrar profil çıkarmak öncekinin üzerine yazar. SQS, RQ ve Celery de aynı mantıkla çalışır.

Kubernetes CI işi bunu gerçekten deniyor:
- worker'lar 0'a indiriliyor,
- bir süreç işi alıp onaylamadan "ölüyor",
- yeni bir worker açılıyor,
- iş kuyruğa geri dönüp bitiyor.

Son çare olarak [`cleanup.py`](../datadigest/cleanup.py) içindeki `fail_stuck` hâlâ duruyor. CronJob, 15 dakikadan uzun süredir bekleyen işleri "failed" yapar. Bu, Redis'in kendisi işi kaybederse diye var.

**Inline mod:** `REDIS_URL` yoksa API işi `BackgroundTasks` ile kendisi yapar. Yerel geliştirme için pratik ama ölçeklenmez.

---

## 3. Veritabanı, ORM ve migration

**Ne:**
- **ORM (SQLAlchemy):** Python sınıflarını tablolara eşler.
- **Migration (Alembic):** Şema değişikliklerini sürümlü dosyalarla yönetir.

**Projede:**
- [`models.py`](../datadigest/models.py)
- [`migrations/versions/0001_initial.py`](../migrations/versions/0001_initial.py)

**Neden `create_all` değil?** `create_all` sadece eksik tabloyu oluşturur, kolon ekleyemez veya değiştiremez. Canlı bir veritabanında şema evrimi için migration gerekir. CI'da migration'ın hem `upgrade` hem `downgrade` yönü test ediliyor.

**Tasarım ayrıntıları:**
- Ham dosya `dataset_files` tablosunda ayrı duruyor. Listeleme sorgusu megabaytlarca veriyi boşuna çekmesin diye.
- `profile` kolonu PostgreSQL'de JSONB, SQLite'ta JSON (`with_variant`).
- SQLite'ta yabancı anahtarlar varsayılan olarak kapalı. [`db.py`](../datadigest/db.py) içinde `PRAGMA foreign_keys=ON` ile açılıyor, yoksa `ON DELETE CASCADE` çalışmaz.

**Şema evrimi örneği:** Kalite skoru sonradan eklendi. Bunun için
[`0002_quality_score.py`](../migrations/versions/0002_quality_score.py) migration'ı mevcut tabloya kolon ekliyor ve şunları gösteriyor:
- **Nullable:** Kolon boş bırakılabilir. Eski satırlar bozulmaz, sadece skorları olmaz. Arayüz de bu durumu "eski sürümle analiz edildi" diye gösterir.
- **`down_revision = "0001"`:** Migration'lar bir zincir oluşturur. Alembic hangi sırayla uygulanacaklarını buradan bilir.
- **`batch_alter_table`:** SQLite eski sürümlerde `DROP COLUMN` desteklemez. Batch modu tabloyu yeniden kurarak geri almayı mümkün kılar.

**Dene:**
- `alembic history`: zinciri görürsün.
- `alembic downgrade 0001`: kolon gider.
- `alembic upgrade head`: kolon geri gelir.

**Veri migration'ı:** [`0003_queued_at.py`](../migrations/versions/0003_queued_at.py) yeni kolonu ekledikten sonra mevcut satırları da doldurur (`UPDATE datasets SET queued_at = created_at`). Şema değişikliği ile veri düzeltmesi aynı migration'da, aynı sırayla yapılır.

---

## 4. Docker: image ve container

**Ne:**
- **Image:** Uygulama + bağımlılıklar + işletim sistemi katmanlarından oluşan, değişmez bir paket.
- **Container:** O image'ın çalışan bir kopyası.

**Projede:** [`Dockerfile`](../Dockerfile)

| Kavram | Bu projede |
|---|---|
| Multi-stage build | 1. aşama wheel'leri derler, 2. aşama sadece kurulu paketleri ve kodu alır. Son image küçük kalır. |
| Katman önbelleği | `requirements.txt` koddan önce kopyalanır. Kod değişince bağımlılıklar yeniden kurulmaz. |
| Non-root | `USER app`. Container ele geçirilse bile root değil. |
| `.dockerignore` | `.venv`, testler ve `.git` image'a girmez. |
| Tek image, çok rol | `CMD` varsayılan olarak API'yi çalıştırır. Worker, migrate ve cleanup aynı image'ı farklı komutla çalıştırır. |

**Dene:**

```bash
docker build -t datadigest:0.6.0 .
docker image ls datadigest
docker history datadigest:0.6.0
```

Sonra kodda bir satır değiştirip tekrar build et. Hangi katmanların önbellekten geldiğine bak.

---

## 5. Docker Compose

**Ne:** Birden fazla container'ı tek dosyada tanımlayıp birlikte başlatır.

**Projede:** [`docker-compose.yml`](../docker-compose.yml)

- `depends_on` + `condition: service_healthy`: API, PostgreSQL gerçekten hazır olana kadar başlamaz.
- `service_completed_successfully`: API ve worker, migration bitmeden başlamaz.
- Servisler birbirine **servis adıyla** ulaşır (`postgres:5432`, `redis:6379`). Compose bir iç DNS sağlar.
- `volumes: pgdata`: veritabanı container silinse de kalır.
- `deploy.replicas: 2`: iki worker. İşlerin aralarında dağıldığını loglardan görebilirsin.

**Dene:**

```bash
docker compose up --build
docker compose logs -f worker
docker compose up -d --scale worker=4
```

Dosya yükleyip hangi worker'ın aldığını izle.

---

## 6. Kubernetes

Compose tek makinede çalışır. Kubernetes aynı fikri bir küme üzerinde, kendi kendini onaran şekilde yapar: sen "istenen durumu" yazarsın, Kubernetes onu sürekli korur.

| Nesne | Ne işe yarar | Projede |
|---|---|---|
| **Namespace** | Kaynakları gruplar, isim çakışmasını önler | [`namespace.yaml`](../k8s/namespace.yaml) |
| **Pod** | Bir veya birkaç container'ın çalışma birimi. Geçicidir. | Deployment'lar oluşturur |
| **Deployment** | "Şu image'dan N pod çalışsın" der. Pod ölürse yenisini açar, güncellemeyi sırayla yapar. | [`api.yaml`](../k8s/api.yaml), [`worker.yaml`](../k8s/worker.yaml) |
| **Service** | Pod'ların IP'si değişir. Service sabit bir isim ve IP verip trafiği **etiketi eşleşen** pod'lara dağıtır. | `api`, `redis` |
| **Headless Service** | `clusterIP: None`. DNS doğrudan pod'u gösterir (veritabanı için). | [`postgres.yaml`](../k8s/postgres.yaml) |
| **StatefulSet** | Kalıcı kimlik (`postgres-0`) ve pod başına kalıcı disk. Veritabanları için. | [`postgres.yaml`](../k8s/postgres.yaml) |
| **PVC** | "Bana 1Gi disk lazım" talebi. Pod silinse de disk kalır. | `volumeClaimTemplates` |
| **ConfigMap** | Gizli olmayan ayarlar, ortam değişkeni olarak enjekte edilir. | [`configmap.yaml`](../k8s/configmap.yaml) |
| **Secret** | Şifreler. Git'e **gerçek** değer girmez, sadece örnek. | [`secret.example.yaml`](../k8s/secret.example.yaml) |
| **Job** | Bir kez çalışıp biten iş | [`migrate-job.yaml`](../k8s/migrate-job.yaml) |
| **CronJob** | Zamanlanmış Job (burada 15 dakikada bir: takılı işleri temizle, eski veriyi sil) | [`cleanup-cronjob.yaml`](../k8s/cleanup-cronjob.yaml) |
| **HPA** | CPU'ya göre pod sayısını otomatik ayarlar | [`worker-hpa.yaml`](../k8s/worker-hpa.yaml) |
| **Ingress** | Kümenin dışından HTTP trafiğini Service'lere yönlendirir | [`ingress.yaml`](../k8s/ingress.yaml) |
| **Kustomize** | Dosyaları birleştirir, ortak namespace/etiket/image tag uygular | [`kustomization.yaml`](../k8s/kustomization.yaml) |

### Probe'lar: liveness ve readiness farkı
- **Readiness** (`/readyz`): "Trafik alabilir miyim?" Veritabanı veya Redis yoksa `503` döner. Kubernetes pod'u Service'ten çıkarır ama **öldürmez**.
- **Liveness** (`/healthz`): "Süreç kilitlendi mi?" Başarısız olursa container **yeniden başlatılır**. Bu yüzden dış servisleri kontrol etmez. Etseydi, veritabanı kısa süre gidince bütün API pod'ları boşuna yeniden başlardı.

### Neden migration bir Job?
API 2 replika ile çalışıyor. Migration'ı API'nin açılışına koysaydık, iki pod aynı anda şemayı değiştirmeye çalışırdı. Job tek sefer çalışır ve PostgreSQL hazır olana kadar `backoffLimit` ile yeniden dener.

### HPA ve `resources.requests`
HPA, "CPU kullanımı request'in %70'ini geçerse pod ekle" diye hesaplar. Request yoksa yüzde hesaplanamaz. Bu yüzden worker'da `requests.cpu` şart. HPA ayrıca **metrics-server** ister (README'ye bak).

### Dene

```bash
kubectl apply -k k8s/
kubectl -n datadigest get all
kubectl -n datadigest delete pod -l app=api
kubectl -n datadigest scale deploy/api --replicas=3
kubectl -n datadigest logs -f deploy/worker
kubectl -n datadigest get hpa -w
kubectl -n datadigest create job --from=cronjob/cleanup cleanup-now
kubectl -n datadigest delete pod postgres-0
```

Her komutta neye bakacağın:
- `get all`: her şeyi gör.
- `delete pod -l app=api`: Deployment yerine yenisini açar mı?
- `scale ... --replicas=3`: elle ölçekle.
- `logs -f deploy/worker`: worker loglarını izle.
- `get hpa -w`: büyük dosyalar yüklerken worker sayısını izle.
- `create job --from=cronjob/cleanup`: CronJob'u beklemeden elle tetikle.
- `delete pod postgres-0`: veri kaybolur mu? (PVC sayesinde kaybolmamalı)

---

## 7. CI (GitHub Actions)

**Ne:** Her push'ta kodu otomatik test eden makine.

**Projede:** [`.github/workflows/ci.yml`](../.github/workflows/ci.yml). Üç job var:
1. **test:**
   - `ruff` (lint + format),
   - birim testleri (SQLite + fakeredis),
   - manifest çapraz kontrolü,
   - `kubeconform` (Kubernetes şema doğrulaması).
2. **integration:** GitHub'ın açtığı **gerçek** PostgreSQL ve Redis container'larına karşı uçtan uca test. Önce migration'lar yukarı, aşağı, tekrar yukarı çalıştırılır.
3. **docker:** Image'ı build eder, container'ı başlatır, [`smoke_test.sh`](../scripts/smoke_test.sh) ile profil ve dört optimizasyonu container içinde çözer.
4. **compose:** Tüm sistemi `docker compose up` ile kaldırır ve duman testini kuyruk üzerinden koşar. İşlerin iki worker container'ına da dağıldığını kontrol eder.
5. **kubernetes:** [kind](https://kind.sigs.k8s.io/) ile GitHub'ın makinesinde **gerçek bir Kubernetes kümesi** kurar. İmajı yükleyip `kubectl apply -k k8s/` yapar, ardından şunları kontrol eder:
   - StatefulSet, migration Job'ı ve Deployment'lar hazır mı,
   - pod'larda yeniden başlatma (crash loop) var mı,
   - duman testi Service üzerinden geçiyor mu,
   - CronJob elle tetiklenince başarıyla bitiyor mu,
   - API ve `postgres-0` pod'ları silinince Kubernetes onları yeniden yaratıyor mu ve veri (PVC sayesinde) kayboluyor mu.

   Bu iş, yerelde Docker olmadan da kümede çalıştığının kanıtı.

**Neden iki test katmanı:** Birim testleri hızlıdır ve her yerde çalışır. Ama SQLite ile PostgreSQL arasında farklar var (JSONB, saat dilimi, foreign key). Entegrasyon testi bunları yakalar.

---

## 8. Güvenlik notları
- **XSS:** Kolon adları kullanıcıdan gelir. Rapor Jinja2 `autoescape` ile, dashboard `textContent` ile yazar. `<script>` adında bir kolon çalışmaz; bunun testi var.
- **Boyut sınırı:** Dosya parça parça okunur, sınır aşılınca hemen 413 döner. Böylece 5 GB'lık dosya belleğe alınmaz.
- **Sırlar:** `k8s/secret.yaml` ve `.env` `.gitignore`'da.
- **Güvenlik başlıkları:** [`main.py`](../datadigest/api/main.py) içindeki middleware her yanıta üç başlık ekler:
  - `X-Content-Type-Options: nosniff`: tarayıcı dosya tipini tahmin etmez.
  - `X-Frame-Options: DENY`: sayfa başka bir sitenin içine gömülemez (clickjacking).
  - `Referrer-Policy: same-origin`: tam URL başka sitelere sızmaz.
- **Yol aşma (path traversal):** Örnek veri ucu dosya adını bir izin listesinden (allow-list) kontrol eder. `../pyproject.toml` gibi bir istek 404 alır; bunun testi var.
- **Non-root container**, Kubernetes'te `runAsNonRoot: true`.

---

## 9. Yöneylem araştırması (optimizasyon)

Profilleme "veride ne var?" sorusunu cevaplar. Optimizasyon ise "bu veriyle en iyi karar ne?" sorusunu. Dört model de [`datadigest/optimize/`](../datadigest/optimize/) altında saf fonksiyonlar olarak duruyor: DB ve HTTP bilmiyorlar.

### Doğrusal programlama (LP) ve gölge fiyat
[`production.py`](../datadigest/optimize/production.py), üretim planını bir LP olarak kuruyor:

- **Amaç:** max Σ kâr·miktar.
- **Kısıtlar:** her kaynak için Σ kullanım·miktar ≤ kapasite.

LP çözülünce her kısıtın bir **dual** değeri de gelir. Buna **gölge fiyat** denir: o kaynaktan bir birim daha olsaydı kâr ne kadar artardı? "Makine saati darboğaz, 1 saat daha 21 TL kazandırır" cümlesi buradan çıkıyor. Test, bu sayının doğruluğunu kapasiteyi 1 artırıp yeniden çözerek kontrol ediyor.

**Neden gölge fiyat her şey değil?** Gölge fiyat sadece küçük değişiklikler için geçerli. Makineyi %50 artırınca bu sefer işçilik bitiyor; bunu what-if eğrisi gösteriyor. Uygulama bu durumda kullanıcıyı açıkça uyarıyor.

### Tam sayılı programlama (MIP) ve LP gevşetmesi
"Yarım sandalye üretilemez" → değişkenler tam sayı olmak zorunda. Bu durumda problem MIP'e dönüşür: çözmesi zordur ve dual değer vermez. Uygulama bu yüzden ayrıca **LP gevşetmesini** (tam sayı şartını kaldırılmış hali) çözüyor ve ondan iki şey elde ediyor:
- gölge fiyatları,
- teorik üst sınırı.

İkisi arasındaki farka **integrality gap** deniyor. "Tam sayı plan, teorik optimumun %0,04 yakınında" cümlesi bu farktan geliyor. Bütçe seçimi ([`knapsack.py`](../datadigest/optimize/knapsack.py)) de aynı fikrin 0/1 hali.

### Ulaştırma problemi ve dual fiyatlar
[`transport.py`](../datadigest/optimize/transport.py) klasik ulaştırma tablosunu okuyor: arz kolonu, talep satırı ve birim maliyetler. Dual değerler iki soruyu cevaplıyor:
- "Ankara'ya 1 birim daha arz 32 TL tasarruf ettirir."
- "Trabzon'a 1 birim daha talep 105 TL ekler."

Trabzon'daki 105 tam olarak boş kapasitesi olan İstanbul'dan Trabzon'a gönderim maliyeti. Ekonomik yorumu bu.

### Atama problemi: Macar algoritması
n kişiyi n işe atamanın n! yolu var; 10 kişide 3,6 milyon. Macar algoritması ([`assignment.py`](../datadigest/optimize/assignment.py), SciPy'nin `linear_sum_assignment`'ı) bunu O(n³)'te kesin olarak çözer. İlginç içgörü: takım optimumu için bazı kişiler en iyi oldukları işi yapmıyor.

### Optimum ile sezgisel yöntem farkı
Her sonuç, insanların gerçekte kullandığı basit kuralla karşılaştırılıyor:

| Problem | Basit kural |
|---|---|
| Üretim planı | En yüksek marjlı ürün önce |
| Ulaştırma | En ucuz rota önce |
| Atama | En iyi eşleşme önce |
| Bütçe seçimi | En iyi değer/maliyet önce |

Fark, optimizasyonun neden işe yaradığının somut kanıtı: örneklerde %5 ile %23 arası.

### Kuyruk teorisi: M/M/c ve Kubernetes
[`capacity.py`](../datadigest/optimize/capacity.py) DataDigest'in kendi worker'larını boyutlandırıyor. Kullanılan büyüklükler:
- λ: dakikadaki iş sayısı,
- μ: bir worker'ın saniyedeki iş hızı,
- c: worker sayısı.

**Erlang C** formülü bir işin beklemek zorunda kalma olasılığını verir. Ortalama bekleme ondan çıkar: Wq = C / (cμ − λ).

- **Doğrusal olmama:** Doluluk %100'e yaklaştıkça bekleme patlar. 4 worker'dan 5'e çıkınca bekleme 3,06 saniyeden 0,71 saniyeye düşüyor.
- **Maliyet optimumu:** worker maliyeti ile bekleme maliyeti arasındaki dengenin en ucuz noktası.
- **HPA bağlantısı:**
  - normal yük için gereken sayı `minReplicas` olur,
  - zirve yük için gereken sayı `maxReplicas` olur.

  Sayfa bunları kopyalanabilir YAML olarak veriyor.
- **Varsayımlar:** M/M/c rastgele gelişler ve üstel dağılımlı servis süreleri varsayar. Ölçülen değişkenlik katsayısı (CV) 1'den büyükse gerçek beklemeler daha uzun olabilir; uygulama bunu da söylüyor.

**Dene:**
1. `/optimize`'da dört örneği çalıştır.
2. Üretim planında "Change inputs" ile makine kapasitesini değiştir ve gölge fiyatın nasıl değiştiğine bak.
3. `/capacity`'de geliş hızını artırıp worker sayısının nasıl sıçradığını izle.

---

## 10. Gözlemlenebilirlik: Prometheus ve Grafana

"Sistem çalışıyor mu, ne kadar hızlı, nerede tıkanıyor?" sorusunu log okuyarak cevaplamak zordur. **Metrik**, zaman içinde ölçülen bir sayıdır. Tanımlar [`metrics.py`](../datadigest/metrics.py) içinde. Üç türü var:

| Tür | Ne | Örnek |
|---|---|---|
| **Counter** | Sadece artar | `datadigest_jobs_total{kind="dataset", status="done"}` |
| **Gauge** | İner çıkar | `datadigest_queue_jobs{state="pending"}` |
| **Histogram** | Değerleri kovalara sayar; yüzdelik hesaplanır | `datadigest_job_duration_seconds` |

**Nasıl toplanıyor:**
- API `/metrics` ucunu sunar. Her worker kendi metriklerini 9100 portunda sunar.
- **Prometheus** bunları 5 saniyede bir çeker (scrape). Worker'ları DNS ile bulur: `worker` adı bütün kopyalara çözülür, yani ölçekleyince ayar değişmez ([`prometheus.yml`](../deploy/prometheus/prometheus.yml)).
- **Grafana** Prometheus'a sorgu atıp panoyu çizer. Pano kod olarak üretiliyor: [`make_dashboard.py`](../deploy/grafana/make_dashboard.py).

**Etiket (label) kardinalitesi:** HTTP metriklerindeki yol etiketi `/api/datasets/{dataset_id}` biçiminde bir şablon. Gerçek id (`/api/datasets/3f2a…`) koysaydık her veri seti için yeni bir zaman serisi oluşurdu ve Prometheus'un belleği şişerdi. Bunun bir testi var.

**Örnek PromQL:**
- `rate(datadigest_http_requests_total[1m])`: saniyedeki istek sayısı.
- `histogram_quantile(0.95, sum by (le) (rate(datadigest_job_duration_seconds_bucket[5m])))`: işlerin %95'i bu süreden kısa bitiyor (p95).
- `sum(datadigest_queue_jobs{state="dead"}) > 0`: ölü mektup var (bir uyarı kuralı adayı).

**Dene:**
1. `docker compose --profile monitoring up --build`
2. http://localhost:3000 adresinde DataDigest panosunu aç, birkaç dosya yükle ve çizgilerin hareket ettiğini izle.
3. `docker compose stop redis` ile Redis'i durdur ve "waits for Redis/PostgreSQL" çizgisinin yükseldiğini gör.

---

## 11. Veri kaybına ve saldırıya karşı: kalıcılık, yedek, kimlik doğrulama

### Redis kalıcılığı (AOF)
Redis varsayılan olarak her şeyi bellekte tutar; yeniden başlayınca kuyruk boşalır. **AOF** (append-only file) her yazma komutunu bir dosyaya ekler, açılışta o dosyadan geri yükler. `appendfsync everysec` dosyayı saniyede bir diske zorlar: en kötü durumda (sert çökme) yaklaşık 1 saniyelik yazma kaybolur. Dosya bir **volume**'da durur (Compose'ta isimli volume, Kubernetes'te [`redis.yaml`](../k8s/redis.yaml) içindeki PVC), yoksa container silinince dosya da gider. `strategy: Recreate` şart: `ReadWriteOnce` bir disk iki pod'a aynı anda bağlanamaz.

CI bunu gerçekten deniyor: worker'lar kapalıyken bir iş kuyruğa atılıyor, Redis pod'u siliniyor, yeni pod açılınca iş hâlâ kuyrukta ve worker açılınca bitiyor.

### Yedek: "geri yüklenmemiş yedek yedek değildir"
[`postgres-backup.yaml`](../k8s/postgres-backup.yaml) her gece `pg_dump` alır ve **hemen geri okur** (`pg_restore --list`). Okunamayan bir dosya bulunursa eski yedekler silinmez. [`restore-check-job.yaml`](../k8s/ops/restore-check-job.yaml) en yeni yedeği ayrı bir deneme veritabanına geri yükleyip tablolardaki satırları sayar; canlı veritabanına dokunmaz. CI'da 7 veri setinin geri geldiği görüldü. Sınır: yedek, veritabanının yanındaki bir diskte duruyor; kümeyi kaybedersen yedeği de kaybedersin. Bunun için yedeği küme dışına kopyalamak gerekir.

### Alarm kuralları ve `promtool`
Metrik toplamak izlemenin yarısı; öbür yarısı "bir şey ters giderse biri haberdar olsun". [`alerts.yml`](../deploy/prometheus/alerts.yml) 9 kural tanımlar. Örnek: `sum(datadigest_queue_jobs{state="dead"}) > 0` için `for: 1m`. **`for`** bir koşulun belirli süre sürekli doğru kalmasını bekler, böylece kısa bir dalgalanma alarm üretmez. Her kural [`alerts_test.yml`](../deploy/prometheus/alerts_test.yml) içinde sentetik metriklerle test edilir: "kuyruk 80 olur ve 8 dakika kalırsa alarm çalmalı; 2 dakikalık bir tepe çalmamalı".

### Kimlik doğrulama: küçük ama doğru yapmak
[`auth.py`](../datadigest/api/auth.py) isteğe bağlı tek bir paylaşılan anahtar (`ACCESS_TOKEN`) getirir. Her satırın bir nedeni var:
- **Çerez, anahtarın kendisini değil HMAC'ini taşır.** Çerez çalınsa bile anahtar ortaya çıkmaz.
- **`HttpOnly`:** sayfadaki JavaScript çerezi okuyamaz (XSS olsa bile çalınmaz).
- **`SameSite=Lax`:** başka bir sitedeki form, tarayıcıya bu çerezi POST/DELETE ile göndertemez. Bu, durum değiştiren çağrıları CSRF'ten korur.
- **`hmac.compare_digest`:** karşılaştırma süresi, kaç karakterin doğru olduğuna bağlı değildir (zamanlama saldırısı).
- **Deneme sınırı:** dakikada 5 yanlış denemeden sonra doğru anahtar bile 429 alır.
- **Açık yönlendirme (open redirect) koruması:** giriş sonrası `?next=` ile yönlendirirken `//evil.example` ve `/\evil.example` reddedilir ([`safeNext`](../datadigest/static/app.js)). Aksi halde saldırgan, girişten sonra kurbanı kendi sitesine gönderen bir bağlantı hazırlayabilir. Bunun tarayıcı testi var.
- **Probe'lar ve `/metrics` açık kalır:** Kubernetes ve Prometheus çerez taşıyamaz.

### Tedarik zinciri
- **Actions SHA'ya sabit.** `actions/checkout@v5` bir etikettir ve taşınabilir; ele geçirilen bir depo aynı etikete kötü kod koyabilir. 40 karakterlik commit SHA'sı değişmez. Yanına yorum olarak sürüm yazılır (`# v5`).
- **Dependabot** her hafta güncelleme PR'ı açar, güvenlik güncellemeleri ayrıca otomatik gelir.
- **Salt okunur iş akışı jetonu:** `permissions: contents: read`.

## 12. Test piramidi: birimden tarayıcıya

| Katman | Nerede | Neyi yakalar | Süre |
|---|---|---|---|
| Birim (SQLite, fakeredis) | `tests/` | Mantık hataları | ~15 sn |
| Entegrasyon (gerçek PostgreSQL/Redis) | `tests/test_integration.py` | SQLite ile PostgreSQL farkları | ~1 dk |
| Tarayıcı (Playwright) | [`tests_e2e/`](../tests_e2e) | JavaScript, form, diyalog, düzen, grafik | ~1 dk |
| Sistem (Compose, kind) | `.github/workflows/ci.yml` | Dağıtım, ağ, kalıcılık, kurtarma | ~3 dk |

**Kapsam (coverage)** bir kodun yüzde kaçının test sırasında çalıştığını ölçer (şu an ~%95, eşik %90). Yüksek kapsam doğruluk garantisi değildir; düşük kapsam ise testsiz bölgeleri gösterir. Bu ölçüm, `cli.py`'nin hiç test edilmediğini ortaya çıkardı.

**Tarayıcı testleri** daha önce yalnızca elle denediğim şeyleri otomatikleştirdi: çoklu dosya yükleme, silme onayı, `Change inputs` formunun eski parametrelerle dolması, 375 piksel genişlikte yatay kaydırma olmaması ve grafiklerin o genişliğe sığması. Yerelde kurulu Edge ile (`E2E_BROWSER_CHANNEL=msedge`), CI'da Chromium ile çalışır. Test başarısız olursa ekran görüntüsü kaydedilir.

---

## 13. Bu projede yakalanan hatalar ve öğrettikleri

Her biri testte ya da tarayıcıda ölçerek bulundu. Hepsi düzeltildi; çoğunun artık bir testi var.

| Hata | Ne öğretti |
|---|---|
| SQLite saat dilimini saklamıyor, tarihler "3 saat önce" görünüyordu | Veritabanları zaman damgasını farklı saklar; API her zaman açık UTC döndürmeli ([`schemas.py`](../datadigest/api/schemas.py)). |
| Grafikler gizli sekmede çizilince 700px'e taşıyordu | Plotly kapsayıcısını ölçer, gizli öğenin genişliği 0'dır; grafik görünür olunca çizilmeli (`IntersectionObserver`). |
| Ulaştırmada "1 birim talep −21 ekler" çıkıyordu | Dual değerin işareti kısıtın yazılış yönüne bağlıdır (≤ ya da ≥). Çözüm: "1 birim artırıp yeniden çöz" testi. |
| Form varsayılanları uygulanamaz bir model kuruyordu | Varsayılan değerler de veridir. Hiç düşünmeden "ortalama × satır" demek yerine minimum talebi karşılayan kapasite hesaplandı. |
| Mobilde Optimize sayfası 776px'e genişliyordu | `position: absolute` bir öğe, en yakın konumlandırılmış ataya göre yerleşir. Kaydırma kutusu konumlandırılmamışsa öğe kutudan kaçar. `backdrop-filter` de yeni bir kapsayıcı blok oluşturur. |
| Düzeltilen CSS tarayıcıya ulaşmadı | Tarayıcı önbelleği. Çözüm: HTML `no-cache` ile sunulur, statik dosyalar sürümlü (`style.css?v=0.6.0`) bağlanır. |
| Örnek CSV'ler git'te "değişmiş" görünüyordu | pandas Windows'ta CRLF yazar. Çıktıyı işletim sisteminden bağımsız yapmak için `lineterminator="\n"`. |
| Kubernetes'te worker pod'u ilk saniyelerde 2 kez yeniden başladı | Pod'lar bağımlılıklarından (Redis, PostgreSQL) önce açılabilir. Çökmek yerine artan bekleme süreleriyle yeniden denemek (exponential backoff) gerekir. CI artık yeniden başlatma sayısının 0 olduğunu kontrol ediyor. |
| Kapasite testi geçti ama yanlış bir şeyi kontrol ediyordu | Test "Recommended workers kutusu `5` içeriyor" diyordu. Varsayılan durumda kutuda zaten "meets **5** s mean wait" yazıyordu. Yanlış pozitif: test, hata olsa da geçerdi. Bir testin gerçekten başarısız olabildiğinden emin ol; değeri tam eşleştir (`to_have_text("5")`). |
| Yeniden çalıştırma testi ara sıra yanlış sonuç verdi | Düğmeye tıklayınca istek hemen gitmez. Test, eski "done" durumunu görüp erken ölçüyordu (**yarış durumu**). Çözüm: durum değil, **yeni bir bitiş zamanı** bekle. |
| Grafikler 375 piksel testinde hiç çizilmedi | Grafikler görünür olunca çizilir (`IntersectionObserver`). Sayfanın sonuna tek hamlede atlayınca grafik hiç görünmeden geçilir. Gerçek kullanıcı kaydırır; test de kademeli kaydırmalı. |
| Release notları boş çıkıyordu | `awk` içindeki regex kaçışları ortama göre farklı yorumlanıyor. Düz metin karşılaştıran `index()` ile kaçış gerekmedi. Betiğin boş çıktı verirse hata vermesi de eklendi. |
| Reddedilen istekler metriklerde görünmüyordu | Starlette'te sonradan eklenen middleware **en dışta** çalışır. Kimlik doğrulama ve metrik sırası önemli: reddedilenleri de saymak için metrik, doğrulamanın dışında olmalı. |
| `sales.csv` ile kâr kolonu testi beklenmedik biçimde başarısız oldu | Veride 5 tekrar eden satır var, `order_id` benzersiz değil. Test, sistemin başka (ve doğru) bir hatayı önce yakaladığını gösterdi. |

Genel ders: "çalışıyor gibi görünüyor" ile "doğru" arasındaki farkı ölçmek gerekiyor. Bunun yolları:
- optimum değerleri kaba kuvvetle karşılaştırmak,
- dual değerleri yeniden çözerek doğrulamak,
- sayfa genişliğini sayıyla ölçmek,
- ekran görüntüsüne gerçekten bakmak.

---

## Mülakatta 60 saniyede anlatım

> "CSV yükleyince otomatik veri kalitesi raporu çıkaran bir servis yazdım. API dosyayı alıp 202 döner ve işi Redis kuyruğuna atar. Worker'lar pandas ile profil çıkarıp PostgreSQL'e JSONB olarak yazar. Analiz CPU-ağır olduğu için worker'ları API'den ayırdım ve Kubernetes'te HPA ile CPU'ya göre ölçekliyorum. Migration'lar Job, eski veri temizliği CronJob. Liveness ile readiness'ı bilerek ayırdım: veritabanı gidince pod'lar trafikten çıkıyor ama yeniden başlamıyor. CI'da hem SQLite ile hızlı birim testleri hem de gerçek PostgreSQL/Redis ile entegrasyon testleri koşuyor. Aynı veriler üzerinde yöneylem araştırması da var: LP/MIP ile üretim planı, ulaştırma, atama ve bütçe seçimi. Her sonuç gölge fiyatlarla açıklanıyor ve basit kurala göre ne kadar daha iyi olduğu gösteriliyor; optimallik testlerde kaba kuvvetle doğrulanıyor. Kuyruk teorisiyle de (M/M/c) uygulamanın kendi worker sayısını ve HPA ayarlarını hesaplıyorum. Kuyruk en az bir kez teslim garantili: worker ölürse iş otomatik olarak geri döner, üç denemeden sonra ölü mektuba düşer. İşleyiciler bu yüzden idempotent. Her şey Prometheus metrikleri ve bir Grafana panosuyla izleniyor."
