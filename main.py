import requests
from bs4 import BeautifulSoup
import os
import logging
from urllib.parse import urljoin, urlparse, parse_qs
import time
import json

# Конфигурация
BASE_URL = "http://publication.pravo.gov.ru"
MAIN_PAGE_URL = f"{BASE_URL}/documents/block/president"
PDF_DIR = "pdfs"
LOG_FILE = "download.log"
TIMEOUT = 45
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3',
}

# Настройка логирования
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)

def setup_environment():
    os.makedirs(PDF_DIR, exist_ok=True)
    logging.info(f"Рабочая директория: {os.getcwd()}")

def debug_save_response(response, page_num):
    debug_dir = "debug_responses"
    os.makedirs(debug_dir, exist_ok=True)
    filename = os.path.join(debug_dir, f"page_{page_num}.html")
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(response.text)
    logging.debug(f"Сохранен ответ страницы {page_num} в {filename}")

def get_total_pages(session):
    try:
        logging.info("Определение общего количества страниц...")
        response = session.get(
            MAIN_PAGE_URL,
            params={"index": 1, "pageSize": 200},
            timeout=TIMEOUT
        )
        response.raise_for_status()
        
        debug_save_response(response, 1)
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Метод 1: Поиск в пагинации
        pagination = soup.find('ul', class_='pagination')
        if pagination:
            last_page_link = pagination.find_all('a')[-2]
            last_page_url = last_page_link.get('href')
            parsed = urlparse(last_page_url)
            return int(parse_qs(parsed.query)['index'][0])
        
        # Метод 2: Поиск текста "Последняя"
        last_page_text = soup.find('a', string='Последняя')
        if last_page_text:
            last_page_url = last_page_text.get('href')
            parsed = urlparse(last_page_url)
            return int(parse_qs(parsed.query)['index'][0])
        
        # Метод 3: Подсчет документов
        total_docs = len(soup.find_all("div", class_="infoindocumentlist"))
        if total_docs == 200:
            logging.warning("Возможно больше одной страницы, установлено значение по умолчанию 87")
            return 87
        
        return 1
        
    except Exception as e:
        logging.error(f"Ошибка определения страниц: {str(e)}")
        return 1

def process_page(session, page_num):
    logging.info(f"▶️ Начало обработки страницы {page_num}")
    try:
        params = {"index": page_num, "pageSize": 200}
        response = session.get(
            MAIN_PAGE_URL,
            params=params,
            timeout=TIMEOUT
        )
        response.raise_for_status()
        
        debug_save_response(response, page_num)
        
        if response.status_code != 200:
            logging.error(f"Страница {page_num}: код {response.status_code}")
            return 0, 0, 0
            
        soup = BeautifulSoup(response.text, 'html.parser')
        blocks = soup.find_all("div", class_="infoindocumentlist")
        
        if not blocks:
            logging.warning(f"Страница {page_num}: нет документов")
            return 0, 0, 0
            
        stats = {'downloaded': 0, 'errors': 0, 'skipped': 0}
        
        for block in blocks:
            time.sleep(0.5)
            try:
                # Поиск номера документа
                number_tag = block.find("span", class_="info-data")
                if not number_tag:
                    logging.debug("Не найден номер документа")
                    continue
                pub_number = number_tag.text.strip()
                
                # Поиск ссылки на PDF
                pdf_link = block.find("a", class_="documents-item-file")
                if not pdf_link or not pdf_link.get('href'):
                    logging.debug(f"Документ {pub_number}: нет ссылки")
                    continue
                
                pdf_url = urljoin(BASE_URL, pdf_link['href'])
                filename = os.path.join(PDF_DIR, f"{pub_number}.pdf")
                
                if os.path.exists(filename):
                    stats['skipped'] += 1
                    logging.debug(f"Пропущен существующий: {pub_number}")
                    continue
                
                # Загрузка PDF
                pdf_response = session.get(
                    pdf_url,
                    stream=True,
                    timeout=TIMEOUT
                )
                
                if pdf_response.status_code == 200:
                    with open(filename, 'wb') as f:
                        for chunk in pdf_response.iter_content(chunk_size=8192):
                            f.write(chunk)
                    stats['downloaded'] += 1
                    logging.info(f"✅ Успешно: {pub_number}")
                else:
                    stats['errors'] += 1
                    logging.error(f"❌ Ошибка {pdf_response.status_code}: {pub_number}")
                
            except Exception as e:
                stats['errors'] += 1
                logging.error(f"Ошибка документа: {str(e)}")
                continue
        
        logging.info(f"✔️ Страница {page_num} завершена: {stats}")
        return stats
        
    except Exception as e:
        logging.error(f"🔥 Критическая ошибка страницы {page_num}: {str(e)}")
        return {'downloaded': 0, 'errors': 1, 'skipped': 0}

def main():
    setup_environment()
    session = requests.Session()
    session.headers.update(HEADERS)
    
    total_pages = get_total_pages(session)
    logging.info(f"Всего страниц для обработки: {total_pages}")
    
    total_stats = {
        'downloaded': 0,
        'errors': 0,
        'skipped': 0,
        'processed_pages': 0
    }
    
    for page_num in range(1, total_pages + 1):
        try:
            page_stats = process_page(session, page_num)
            total_stats['downloaded'] += page_stats['downloaded']
            total_stats['errors'] += page_stats['errors']
            total_stats['skipped'] += page_stats['skipped']
            total_stats['processed_pages'] += 1
            
            # Сохраняем промежуточные результаты
            with open('progress.json', 'w') as f:
                json.dump(total_stats, f)
            
            time.sleep(3)
            
        except KeyboardInterrupt:
            logging.info("⏹ Прервано пользователем")
            break
            
        except Exception as e:
            logging.error(f"💣 Фатальная ошибка: {str(e)}")
            continue
    
    logging.info("\n📊 Итоговая статистика:")
    logging.info(f"Обработано страниц: {total_stats['processed_pages']}/{total_pages}")
    logging.info(f"Успешно скачано: {total_stats['downloaded']}")
    logging.info(f"Ошибок: {total_stats['errors']}")
    logging.info(f"Пропущено: {total_stats['skipped']}")
    logging.info(f"Файлов в папке: {len(os.listdir(PDF_DIR))}")

if __name__ == "__main__":
    main()
