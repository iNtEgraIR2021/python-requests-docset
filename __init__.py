
import logging
import os
from pathlib import Path
from pprint import pprint
import json
import re
import sys
import zipfile

from bs4 import BeautifulSoup, Comment
import css_parser
import htmlmin
import requests

logging.basicConfig(level=logging.DEBUG)

css_parser.log.setLevel(logging.INFO)

zip_file = Path("requests-latest.zip")

logging.debug(f"requesting '{zip_file}' ... ")

dl_req = requests.get(f"https://requests.readthedocs.io/_/downloads/en/latest/htmlzip/", stream=True)
if dl_req.ok:
    with open(zip_file, 'wb') as f:
        for chunk in dl_req:
            f.write(chunk)
else:
    print(f"ERROR: download failed -> request returned unexpected status code '{dl_req.status_code}' ")
    sys.exit(1)

logging.debug(f"download of '{zip_file}' (size: {zip_file.stat().st_size} bytes) completed ")

logging.debug(f"extracting '{zip_file}' ... ")

with zipfile.ZipFile(zip_file, 'r') as zip_fh:
    zip_fh.extractall()

logging.debug(f"extracted '{zip_file}'")

logging.debug(f"executing 'doc2dash' ... ")

os.system(f"doc2dash -n Requests -i requests-latest/_static/requests-sidebar.png -f -I index.html requests-latest/")

logging.debug(f"executed 'doc2dash'")

docset_path = Path('Requests.docset')

if not docset_path.exists():
    logging.error(f"while trying to access '{docset_path}' -> 'exists' is '{docset_path.exists()}' ")
    sys.exit(1)

docset_size = docset_path.stat().st_size

if docset_size < 2:
    logging.error(f"while trying to read contents of '{docset_path}' -> 'size' is '{docset_size} bytes' ")
    sys.exit(1)

logging.debug(f"size of '{docset_path}' is '{docset_size} bytes' ")

documents_path = docset_path / "Contents" / "Resources" / "Documents"

index_path = documents_path / "index.html"

if not index_path.exists():
    logging.error(f"while trying to access '{index_path}' -> 'exists' is '{index_path.exists()}' ")
    sys.exit(1)

index_size = index_path.stat().st_size

if index_size < 2:
    logging.error(f"while trying to read contents of '{index_path}' -> 'size' is '{index_size} bytes' ")
    sys.exit(1)

logging.debug(f"size of '{index_path}' is '{index_size} bytes' ")

index_html = ''

logging.debug(f"reading from '{index_path}' ... ")

index_old_size = index_path.stat().st_size

with open(index_path, 'r', encoding='utf-8') as fh:
    index_html = str(fh.read())

index_len = len(index_html)

logging.debug(f"reading from '{index_path}' (length: {index_len}) completed ")

docset_soup = BeautifulSoup(str(index_html), features='html.parser')

logging.debug(f"removing interactive contents ...")

for tag_selector in [docset_soup.select('#searchbox'), docset_soup.select('script'), docset_soup.select('iframe'), docset_soup.select('#native-ribbon'), docset_soup.select('a.github'), docset_soup.select('a.reference.external.image-reference'), docset_soup.select('link[rel="search"]'), docset_soup.select('link[rel="index"]')]:
    for tag in tag_selector:
        tag.decompose()

index_len = len(index_html)

logging.debug(f"removed interactive contents -> new length: {index_len} ")

viewport_tags = docset_soup.select('meta[name="viewport"]')
if len(viewport_tags) == 2:
    viewport_tags[1].decompose()
    logging.debug(f"removed surplus 'viewport' tag ")

static_files_path = documents_path / "_static"

js_files = list(static_files_path.glob('*.js'))

logging.debug(f"found {len(js_files)} obsolete javascript files")
#pprint(js_files)
for js_file in js_files:
    try:
        js_file.unlink()
    except Exception as e:
        logging.error(f"failed to delete '{js_file}' -> error: {e}")

css_links = docset_soup.select('link[rel="stylesheet"]')
css_styles = ''
import_pattern = re.compile(r'(?m)(\@import url\(\")([^\"]+)(\"\)\;)')

for css_link in css_links:
    link_href = str(css_link.get('href'))
    link_path = documents_path / Path(link_href)
    logging.debug(f"validating existance of '{link_path}' ... ")
    if not link_path.exists():
        logging.debug(f"removing '{css_link}' -> source file does not seem to exist")
        css_link.decompose()
    else:
        logging.debug(f"found '{link_path}' (size: {link_path.stat().st_size}) ")

        logging.debug(f"reading from '{link_path}' ... ")

        css_rules = ''
        with open(link_path, 'r', encoding='utf-8') as fh:
            css_rules = '\n' + str(fh.read())

        logging.debug(f"reading from '{link_path}' (length: {link_path.stat().st_size}) completed ")

        css_imports = list(re.findall(import_pattern, css_rules))
        if len(css_imports) > 0:
            for css_import in css_imports:
                import_path = static_files_path / Path(str(css_import[1]))
                if import_path.exists():
                    logging.debug(f"reading from '{import_path}' ... ")

                    with open(import_path, 'r', encoding='utf-8') as fh:
                        css_rules = '\n' + str(fh.read()) + '\n' + css_rules

                    logging.debug(f"reading from '{import_path}' (length: {import_path.stat().st_size}) completed ")
                else:
                    logging.debug(f"reading from '{import_path}' failed -> file does not seem to exist ")

        css_styles += css_rules

for style_tag in docset_soup.select('style'):
    css_styles += '\n'+str(style_tag.text).strip()
    style_tag.decompose()

css_min_file = "styles.min.css"
css_min_path = static_files_path / css_min_file
last_link = docset_soup.select('link[rel="stylesheet"]')[-1]
last_link['href'] = '_static/' + css_min_file
last_link['type'] = 'text/css'
del last_link['media']

css_links = docset_soup.select('link[rel="stylesheet"]')
for link_index in range(len(css_links)-1): # remove all other 'link' tags
    css_links[link_index].decompose()

css_styles = re.sub(import_pattern,'',css_styles) # remove obsolete imports -> after merging all files

styles_parser = css_parser.CSSParser(raiseExceptions=False)
css_sheet = styles_parser.parseString(css_styles)

remove_rules = []
removed_counter = 0
for css_rule in css_sheet:
    try:
        if hasattr(css_rule, 'media'):
            remove_rules2 = []
            for css_rule2 in css_rule:
                css_select = str(css_rule2.selectorText)
                if ':before' not in css_select and ':after' not in css_select: # both are not implemented -> see https://github.com/facelessuser/soupsieve/issues/198
                    tag_matches = docset_soup.select(css_select)
                    if len(tag_matches) == 0:
                        #print(css_select)
                        remove_rules2.append(css_rule2)

            for css_rule2 in remove_rules2:
                css_rule.cssRules.remove(css_rule2)
                removed_counter += 1

            continue
        elif hasattr(css_rule, 'selectorText'):
            css_select = str(css_rule.selectorText)
            if ':before' not in css_select and ':after' not in css_select: # both are not implemented -> see https://github.com/facelessuser/soupsieve/issues/198
                tag_matches = docset_soup.select(css_select)
                if len(tag_matches) == 0:
                    #print(css_select)
                    remove_rules.append(css_rule)
        else:
            #print(css_rule)
            remove_rules.append(css_rule)
    except Exception as e:
        logging.error(f"processing of css rule '{css_rule}' failed -> error: {e}")

for css_rule in remove_rules:
    css_sheet.cssRules.remove(css_rule)

logging.debug(f"removed {removed_counter + len(remove_rules)} obsolete css rules")

old_css_len = len(css_styles)
css_styles = str(css_sheet.cssText.decode())

css_styles = str(re.sub(r'(?m)[\n\r]+', '', css_styles))
css_styles = str(re.sub(r'(?m)( ){2}', '', css_styles))

new_css_len = len(css_styles)

css_files = list(static_files_path.glob('*.css'))

logging.debug(f"found {len(css_files)} obsolete css files")
#pprint(js_files)
for css_file in css_files:
    try:
        css_file.unlink()
    except Exception as e:
        logging.error(f"failed to delete '{css_file}' -> error: {e}")

css_len_diff = old_css_len - new_css_len
css_len_percent = css_len_diff / old_css_len * 100
logging.debug(f"reduced size of css by {css_len_diff} characters (to ca. {round(css_len_percent, 1)} percent of original) ")

with open(css_min_path, 'w+', encoding='utf-8') as fh:
    fh.write(css_styles)

for tag in docset_soup.body.children:
    if isinstance(tag, Comment): # remove html comments
        tag.decompose()

index_html = str(docset_soup)

logging.debug(f"writing to '{index_path}' ... ")

try:
    with open(index_path, "w+", encoding="utf-8") as fh:
        fh.write(htmlmin.minify(index_html, remove_empty_space=True))
except Exception as e:
    logging.error("minification of '"+index_path+"' failed -> error: "+str(e))
    with open(index_path, 'w+', encoding='utf-8') as fh:
        fh.write(index_html)

index_new_size = index_path.stat().st_size
index_len_diff = index_old_size - index_new_size

logging.debug(f"writing to '{index_path}' completed -> reduced size by {index_len_diff} bytes ")

img_files = list(static_files_path.glob('*.png')) + list(static_files_path.glob('*.jpg')) + list(static_files_path.glob('*.svg'))

logging.debug(f"found {len(img_files)} images (.png, .jpg, .svg) in '{static_files_path}' ")

for img_file in img_files:
    try:
        file_name = str(img_file.stem + img_file.suffix)
        if file_name in index_html:
            continue
        if file_name in css_styles:
            continue
        else:
            logging.debug(f"removing image '{img_file}' -> file name '{file_name}' has not been found in css or html")
            try:
                img_file.unlink()
            except Exception as e:
                logging.error(f"failed to delete '{img_file}' -> error: {e}")
    except Exception as e:
        logging.error(f"failed to validate existance of '{img_file}' -> error: {e}")

sys.exit(0)

meta_path = docset_path / "meta.json"

if not meta_path.exists():
    logging.debug(f"preparing contents of '{meta_path}' ... ")

    requests_version = '2.28.1'

    meta_json = {
        "feed_url": "https://zealusercontributions.vercel.app/api/docsets/Requests.xml",
        "name": "Requests",
        "title": "Requests",
        "urls": [
            "https://kapeli.com/feeds/zzz/user_contributed/build/Requests/Requests.tgz",
            "https://sanfrancisco.kapeli.com/feeds/zzz/user_contributed/build/Requests/Requests.tgz",
            "https://newyork.kapeli.com/feeds/zzz/user_contributed/build/Requests/Requests.tgz",
            "https://london.kapeli.com/feeds/zzz/user_contributed/build/Requests/Requests.tgz",
            "https://frankfurt.kapeli.com/feeds/zzz/user_contributed/build/Requests/Requests.tgz"
        ],
        "version": requests_version
    }

    with open(meta_path, 'w+', encoding='utf-8') as fh:
        fh.write(json.dumps(meta_json))

    logging.debug(f"wrote contents of '{meta_path}' ")