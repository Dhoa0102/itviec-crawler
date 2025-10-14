import os
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import pandas as pd
import time, gc, re, sys, warnings
from datetime import datetime, timedelta

# Tắt warning lặt vặt
if not sys.warnoptions:
    warnings.simplefilter("ignore")


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


def crawl_itviec_jobs(pages=1, headless=False):
    """Crawl ITviec job listings and return a pandas DataFrame"""
    options = uc.ChromeOptions()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    driver = uc.Chrome(options=options)
    wait = WebDriverWait(driver, 12)

    base_url = "https://itviec.com/it-jobs"
    rows = []

    try:
        for page in range(1, pages + 1):
            print(f"🔍 Đang crawl trang {page}...")
            driver.get(f"{base_url}?page={page}")
            wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div.job-card")))
            time.sleep(3)

            job_cards = driver.find_elements(By.CSS_SELECTOR, "div.job-card")
            if len(job_cards) < 10:
                print("⚠️ Trang chưa load đủ job, đợi thêm 2s...")
                time.sleep(2)
                job_cards = driver.find_elements(By.CSS_SELECTOR, "div.job-card")

            for idx, card in enumerate(job_cards, 1):
                try:
                    job_link = card.get_attribute("data-search--job-selection-job-url-value") or ""
                    if job_link and job_link.startswith("/"):
                        job_link = "https://itviec.com" + job_link

                    # job_category
                    try:
                        job_category = card.find_element(
                            By.CSS_SELECTOR, "div.imt-1 a.position-relative.stretched-link.text-rich-grey"
                        ).text.strip()
                    except Exception:
                        try:
                            job_category = card.find_element(
                                By.XPATH,
                                ".//div[contains(@class,'imt-1')]//a[starts-with(@href,'/it-jobs/') and not(contains(@class,'itag'))]",
                            ).text.strip()
                        except Exception:
                            job_category = ""

                    # location
                    try:
                        loc_elems = card.find_elements(By.CSS_SELECTOR, "div.text-rich-grey.text-truncate.text-nowrap")
                        locations = [l.text.strip() for l in loc_elems if l.text.strip()]
                        location = "; ".join(locations)
                    except Exception:
                        location = ""

                    try:
                        card_title = card.find_element(By.CSS_SELECTOR, "h3").text.strip()
                    except Exception:
                        card_title = ""

                    # mở preview
                    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", card)
                    time.sleep(0.5)
                    driver.execute_script("arguments[0].click();", card)
                    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.preview-job-wrapper")))
                    time.sleep(1)

                    preview = driver.find_element(By.CSS_SELECTOR, "div.preview-job-wrapper")

                    try:
                        preview_link_el = preview.find_element(By.CSS_SELECTOR, "a[data-job-id]")
                        job_link = preview_link_el.get_attribute("href") or job_link
                    except Exception:
                        pass

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

                    # title + company
                    job_title = safe("div.preview-job-header h2.text-it-black")
                    company_name = safe("div.preview-job-header span a.normal-text") or safe(
                        "section.company-infos h2 a"
                    )

                    # work mode
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

                    # date posted
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

                    skills_required = ", ".join(safe_all("section.preview-job-overview .d-flex.flex-wrap a.itag"))

                    rows.append(
                        {
                            "job_title": job_title,
                            "company_name": company_name,
                            "location": location,
                            "skills_required": skills_required,
                            "date_posted": date_posted,
                            "job_link": job_link,
                            "job_category": job_category,
                            "work_mode": work_mode,
                        }
                    )
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


if __name__ == "__main__":
    print(">>> Bắt đầu crawl ITviec...")
    df = crawl_itviec_jobs(pages=3, headless=True)  # chỉ crawl 3 trang để test
    output_path = os.path.join(os.getcwd(), "itviec_jobs_full.csv")
    df.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"✅ Đã lưu file CSV tại: {output_path}")
    print(f"✅ Tổng số dòng crawl được: {len(df)}")
