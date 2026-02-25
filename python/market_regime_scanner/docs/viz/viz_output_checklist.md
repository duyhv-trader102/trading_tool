# Viz Output Checklist

Danh sách kiểm tra khi tạo mới hoặc sửa bất kỳ file sinh HTML / TPO chart
(observer, scanner, daily_scan, tracker, v.v.)

---

## 1. Sinh HTML trong memory

```python
html = visualize_tpo_topdown(
    mtf_results=mtf_results,
    filename=output_file,   # dùng để log, không write ở đây
    symbol=symbol,
    return_html=True,       # ← BẮT BUỘC: trả string, không tự write
)
if not html:
    return None
```

- [ ] Luôn dùng `return_html=True` — giữ HTML trong memory trước
- [ ] Kiểm tra `if not html` ngay sau khi gọi

---

## 2. Ghi file local TRƯỚC (bắt buộc)

```python
os.makedirs(os.path.dirname(output_file), exist_ok=True)
with open(output_file, "w", encoding="utf-8") as fh:
    fh.write(html)
```

- [ ] `makedirs(..., exist_ok=True)` trước khi write
- [ ] Encoding luôn là `"utf-8"`
- [ ] Ghi local **trước** S3 — không phụ thuộc S3 availability
- [ ] Với Plotly: `fig.write_html(filename, include_plotlyjs="cdn")`
  - `"cdn"` giữ file nhỏ, load nhanh; dùng `"inline"` chỉ khi cần offline

---

## 3. Upload S3 — backup, không phải primary

```python
try:
    from infra.s3_storage import _get_singleton
    s3 = _get_singleton()
    if s3 is not None:
        key = s3._report_key(output_file)
        s3.client.put_object(
            Bucket=s3._bucket, Key=key,
            Body=html.encode("utf-8"),
            ContentType="text/html",
        )
except Exception as exc:
    logger.debug("S3 upload failed: %s", exc)
```

- [ ] S3 upload nằm trong `try/except` — lỗi không được crash
- [ ] Không dùng presigned URL làm link trong dashboard (link expires 300s)  
- [ ] `return None` sau khi write local — caller dùng relative path local
- [ ] Nếu cần bulk backup cả thư mục: dùng `backup_report_dir(base_dir)` ở cuối scan

---

## 4. Cấu trúc thư mục output

```
output/daily/{YYYY-MM-DD}/{market_lower}/
    dashboard.html              ← main dashboard
    binance/
        BTCUSDT_TPO_TopDown.html
    fx/
        XAUUSDm_TPO_TopDown.html
```

```python
# Daily scan pattern
base_dir    = ROOT / args.output_dir / today_str          # e.g. output/daily/2026-02-25
market_dir  = base_dir / market.lower()                   # e.g. output/daily/.../binance
output_file = str(market_dir / f"{safe_sym}_TPO_TopDown.html")
```

- [ ] Tên file: `{symbol}_TPO_TopDown.html` (replace `/` và `:` → `_`)
- [ ] Dùng `Path` thay `os.path.join` cho readability
- [ ] `market_dir.mkdir(parents=True, exist_ok=True)` trước khi generate

---

## 5. Gắn kết quả chart vào result dict

```python
chart_file = sym.replace("/", "_").replace(":", "_") + "_TPO_TopDown.html"
r["has_chart"] = (market_dir / chart_file).exists()
# r["chart_url"] chỉ set nếu có presigned URL hợp lệ (không set = dùng local path)
```

- [ ] `has_chart` = `True/False` — dashboard dùng để quyết định có render link không
- [ ] `chart_url` = presigned S3 URL nếu có (optional). Nếu không set, reporting.py tự dùng relative path
- [ ] Relative path trong dashboard: `{market.lower()}/{symbol}_TPO_TopDown.html`  
  → link hoạt động vì dashboard.html nằm cùng thư mục cha với `binance/`, `fx/`, v.v.

---

## 6. Mở browser

```python
# CLI flag
parser.add_argument("--no-open", action="store_true", help="Don't auto-open in browser")

# Mở local file — dùng .as_uri() không dùng string path trực tiếp
if not args.no_open:
    import webbrowser
    webbrowser.open(Path(output_file).as_uri())
```

- [ ] Luôn có flag `--no-open` để tắt auto-open (dùng trong CI / headless)
- [ ] Dùng `Path(f).as_uri()` để mở local file (cho Windows: `file:///D:/...`)
- [ ] Không dùng presigned S3 URL để open — link hết hạn sau 300s

---

## 7. Encoding / Windows compatibility

- [ ] Không dùng ký tự Unicode đặc biệt trong print/f-string chạy trên terminal Windows:
  - `→` → dùng `->` 
  - `—` → dùng `--`  
  - `✓` → dùng `[ok]`
- [ ] HTML template: dùng HTML entities thay Unicode trực tiếp:
  - `★` → `&#9733;`  |  `→` → `&rarr;`  |  `—` → `&mdash;`
- [ ] f-string trong `_render_html`: double-brace `{{` `}}` cho CSS/JS literals

---

## 8. Luồng chuẩn (daily_scan / scanner)

```
1. scan_market()
   ├─ generate_tpo_chart(sym)   → write local → S3 backup → return None
   └─ r["has_chart"] = True/False

2. DashboardReporter.generate_dashboard(all_results, ..., diff_report=diff_report)
   └─ dashboard.html ghi local

3. backup_report_dir(base_dir)  → upload toàn bộ thư mục lên S3 (archival)

4. webbrowser.open(dashboard_path.as_uri())
```

- [ ] S3 backup chạy **sau** khi tất cả file local đã được generate
- [ ] `diff_report` được tính và truyền vào `generate_dashboard`
- [ ] Print summary READY signals trước khi open browser

---

## 9. Quick reference — các hàm/class chính

| Mục đích | Hàm / Class | File |
|---|---|---|
| Vẽ TPO chart (topdown) | `visualize_tpo_topdown()` | `viz/tpo_visualizer.py` |
| Vẽ TPO blocks đơn giản | `visualize_tpo_blocks()` | `viz/tpo_visualizer.py` |
| Generate chart + write + S3 | `BaseVizTPOChart.generate_tpo_chart()` | `markets/base/viz_tpo_chart.py` |
| Dashboard HTML | `DashboardReporter.generate_dashboard()` | `markets/reporting.py` |
| S3 bulk backup | `backup_report_dir(dir)` | `infra/s3_storage.py` |
| Signal diff panel | `DiffReport` / `SignalDiff.compare()` | `infra/signal_diff.py` |
| Output path helper | `get_output_path()` | `core/path_manager.py` |
