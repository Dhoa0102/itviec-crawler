import os
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import pandas as pd
import time, gc, re, sys, warnings
from datetime import datetime, timedelta

# ---------------- CONFIG ----------------
# Tắt warning nhỏ
if not sys.warnoptions:
    warnings.simplefilter("ignore")

# Tự phát hiện đang chạy trên GitHub Actions hay local
IS_CI = os.getenv("GITHUB_ACTIONS", "false") == "true"
HEADLESS_MODE = True if IS_CI else False
MAX_PAGES = 56  # có thể đổi thành None nếu muốn crawl tới hết trang

# ---------------- UTILITIES ----------------
def parse_relative_time(text: str) -> str:
    """Convert '15 hours ago' / '33 minutes ago' / '2 days ago' -> 'YYYY-MM-DD HH:MM:SS'"""
    now = datetime.now()
    if not text:
        return now.strftime("%Y-%m-%d %H:%M:%S")
    t = text.lower().strip()
    try:
        n = int(re.search(r"(\d+)", t).group(1))
        if "minute" in t:
            dt = now - timedelta(minutes=n)
        elif "hour" in t:
            dt = now - timedelta(hours=n)
        elif "day" in t:
            dt = now - timedelta(days=n)
        else:
            dt = now
    except Exception:
        dt = now
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def create_chrome_driver(headless=True):
    """Khởi tạo Chrome driver tương thích cho môi trường CI (GitHub Actions)"""
    import shutil, subprocess
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service

    # ✅ Đảm bảo Chromium + Chromedriver tương thích
    subprocess.run(
        "sudo apt-get update && sudo apt-get install -y chromium-browser chromium-chromedriver",
        shell=True,
        check=True,
    )

    # ✅ Copy chromedriver ra vùng tạm có quyền ghi
    tmp_driver = "/tmp/chromedriver"
    shutil.copy("/usr/bin/chromedriver", tmp_driver)
    subprocess.run(f"chmod +x {tmp_driver}", shell=True)

    # ✅ Cấu hình Chrome Options (chuẩn headless cho CI)
    options = webdriver.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-software-rasterizer")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--remote-debugging-port=9222")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--log-level=3")
    if headless:
        options.add_argument("--headless=new")

    print("✅ Using Chromium from:", subprocess.getoutput("chromium-browser --version"))
    print("✅ Using ChromeDriver from:", tmp_driver)

    # ✅ Dùng Selenium gốc (không dùng undetected_chromedriver)
    service = Service(tmp_driver)
    driver = webdriver.Chrome(service=service, options=options)
    driver.implicitly_wait(10)
    return driver

# ---------------- MAIN CRAWLER ----------------
def crawl_itviec_jobs(pages=1, headless=True):
    """Crawl danh sách việc làm ITviec"""
    driver = create_chrome_driver(headless=headless)
    wait = WebDriverWait(driver, 15)
    base_url = "https://itviec.com/it-jobs"
    rows = []

    try:
        for page in range(1, pages + 1):
            print(f"🔍 Đang crawl trang {page}...")
            driver.get(f"{base_url}?page={page}")
            time.sleep(5)

            try:
                wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div.job-card")))
            except Exception:
                print(f"⚠️ Trang {page} không load đủ job-card, bỏ qua...")
                continue

            job_cards = driver.find_elements(By.CSS_SELECTOR, "div.job-card")
            if len(job_cards) == 0:
                print(f"⚠️ Không có job nào ở trang {page}, dừng lại.")
                break

            for idx, card in enumerate(job_cards, 1):
                try:
                    job_link = card.get_attribute("data-search--job-selection-job-url-value") or ""
                    if job_link and job_link.startswith("/"):
                        job_link = "https://itviec.com" + job_link

                    # Category
                    try:
                        job_category = card.find_element(
                            By.CSS_SELECTOR, "div.imt-1 a.position-relative.stretched-link.text-rich-grey"
                        ).text.strip()
                    except Exception:
                        job_category = ""

                    # Location
                    try:
                        loc_elems = card.find_elements(By.CSS_SELECTOR, "div.text-rich-grey.text-truncate.text-nowrap")
                        locations = [l.text.strip() for l in loc_elems if l.text.strip()]
                        location = "; ".join(locations)
                    except Exception:
                        location = ""

                    # Click để mở preview
                    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", card)
                    time.sleep(0.5)
                    driver.execute_script("arguments[0].click();", card)
                    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.preview-job-wrapper")))
                    time.sleep(1)

                    preview = driver.find_element(By.CSS_SELECTOR, "div.preview-job-wrapper")

                    def safe(css, attr=None):
                        try:
                            el = preview.find_element(By.CSS_SELECTOR, css)
                            return el.get_attribute(attr).strip() if attr else el.text.strip()
                        except Exception:
                            return ""

                    def safe_all(css):
                        try:
                            return [el.text.strip() for el in preview.find_elements(By.CSS_SELECTOR, css)]
                        except Exception:
                            return []

                    # Title + Company
                    job_title = safe("div.preview-job-header h2.text-it-black")
                    company_name = safe("div.preview-job-header span a.normal-text") or safe(
                        "section.company-infos h2 a"
                    )

                    # Work mode
                    work_mode = ""
                    try:
                        wm_candidates = preview.find_elements(
                            By.XPATH,
                            ".//section[contains(@class,'preview-job-overview')]//span"
                            "[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'office')"
                            " or contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'remote')"
                            " or contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'hybrid')]",
                        )
                        for el in wm_candidates:
                            txt = el.text.strip()
                            if txt:
                                work_mode = txt
                                break
                    except Exception:
                        pass

                    # Date posted
                    try:
                        clock_span = preview.find_element(
                            By.XPATH,
                            ".//section[contains(@class,'preview-job-overview')]"
                            "//*[name()='use' and contains(@href,'#clock')]"
                            "/ancestor::*[name()='svg']/following-sibling::span",
                        )
                        date_posted = parse_relative_time(clock_span.text.strip())
                    except Exception:
                        date_posted = parse_relative_time("")

                    # Skills
                    skills_required = ", ".join(safe_all("section.preview-job-overview .d-flex.flex-wrap a.itag"))

                    rows.append({
                        "job_title": job_title,
                        "company_name": company_name,
                        "location": location,
                        "skills_required": skills_required,
                        "date_posted": date_posted,
                        "job_link": job_link,
                        "job_category": job_category,
                        "work_mode": work_mode,
                    })

                    print(f"✅ Trang {page} - Job {idx}/{len(job_cards)}")
                except Exception as e:
                    print(f"⚠️ Lỗi job {idx} trang {page}: {e}")
                    continue
    finally:
        try:
            driver.quit()
        except Exception:
            pass
        gc.collect()

    return pd.DataFrame(rows)


# ---------------- MAIN ----------------
if __name__ == "__main__":
    print("🚀 Bắt đầu crawl ITviec...")

    df = crawl_itviec_jobs(pages=MAX_PAGES, headless=HEADLESS_MODE)

    crawl_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    df["crawl_date"] = crawl_date

    output_path = os.path.join(os.getcwd(), "itviec_jobs_full.csv")
    df.to_csv(output_path, index=False, encoding="utf-8-sig")

    print(f"✅ Crawl xong {len(df)} việc làm.")
    print(f"📁 Đã lưu file CSV tại: {output_path}")
