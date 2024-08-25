import logging
import os
from pathlib import Path
import json
import re
import sys
import shutil
import zipfile

import css_parser
import htmlmin
import loguru
import requests
from selectolax.parser import HTMLParser

from logging_interceptor import InterceptHandler

logger = loguru.logger
logger.remove()
# init rotated log file
logger.add(
    "debug.log",
    rotation="10 MB",
    retention="7 days",
    backtrace=True,
    catch=True,
    delay=True,
    encoding="utf-8",
)
# also log to standard output (console)
logger.add(sys.stdout, colorize=True)

logging.basicConfig(handlers=[InterceptHandler()], level=logging.DEBUG, force=True)

css_parser.log.setLevel(logging.INFO)

parent_dir = Path(__file__).parent
zip_file = parent_dir / "requests-stable.zip"
zip_name = zip_file.parts[-1]

logger.debug(f"downloading '{zip_name}' to {zip_file.absolute().as_posix()} ...")

dl_req = requests.get(
    "https://requests.readthedocs.io/_/downloads/en/stable/htmlzip/",
    stream=True,
    timeout=50,
)
if dl_req.ok:
    with open(zip_file, "wb") as file_handle:
        for chunk in dl_req:
            file_handle.write(chunk)
else:
    logger.critical(
        f"download failed -> request returned unexpected status code '{dl_req.status_code}'"
    )
    print(dl_req.text)
    sys.exit(1)

logger.debug(
    f"download of '{zip_file}' (size: {zip_file.stat().st_size} bytes) completed"
)

logger.debug(f"extracting '{zip_file}' ...")

with zipfile.ZipFile(zip_file, "r") as zip_fh:
    zip_fh.extractall()

logger.debug(f"extracted '{zip_file}'")

logger.debug("executing 'doc2dash' ...")

os.system(
    f"doc2dash -n Requests -i {zip_file.stem}/_static/requests-sidebar.png -f -I index.html {zip_file.stem}/"
)

logger.debug("executed 'doc2dash'")

docset_path = Path("Requests.docset")

if not docset_path.exists():
    logger.error(
        f"while trying to access '{docset_path}' -> 'exists' is '{docset_path.exists()}'"
    )
    sys.exit(1)

docset_size = docset_path.stat().st_size

if docset_size < 2:
    logger.error(
        f"while trying to read contents of '{docset_path}' -> 'size' is '{docset_size} bytes'"
    )
    sys.exit(1)

logger.debug(f"size of '{docset_path}' is '{docset_size} bytes'")

documents_path = docset_path / "Contents" / "Resources" / "Documents"

index_path = documents_path / "index.html"

if not index_path.exists():
    logger.error(
        f"while trying to access '{index_path}' -> 'exists' is '{index_path.exists()}'"
    )
    sys.exit(1)

index_size = index_path.stat().st_size

if index_size < 2:
    logger.error(
        f"while trying to read contents of '{index_path}' -> 'size' is '{index_size} bytes'"
    )
    sys.exit(1)

logger.debug(f"size of '{index_path}' is '{index_size} bytes'")

index_html = ""

logger.debug(f"reading from '{index_path}' ...")

index_old_size = index_path.stat().st_size

with open(index_path, "r", encoding="utf-8") as file_handle:
    index_html = str(file_handle.read())

index_len = len(index_html)

logger.debug(f"reading from '{index_path}' (length: {index_len}) completed")

dom_tree = HTMLParser(str(index_html))

logger.debug("removing interactive contents ...")

# docs: https://selectolax.readthedocs.io/en/latest/parser.html#selectolax.parser.HTMLParser.strip_tags
dom_tree.strip_tags(
    [
        "iframe",
        "script",
        "video",
        "#searchbox",
        "#native-ribbon",
        "a.github",
        "a.reference.external.image-reference",
        'link[rel="search"]',
        'link[rel="index"]',
    ]
)

index_len = len(dom_tree.html)
logger.debug(f"removed interactive contents -> new length: {index_len} ")

viewport_tags = dom_tree.css('meta[name="viewport"]')
if len(viewport_tags) == 2:
    viewport_tags[1].decompose()
    logger.debug("removed surplus 'viewport' tag")

static_files_path = documents_path / "_static"

js_files = list(static_files_path.glob("*.js"))

logger.debug(f"found {len(js_files)} obsolete javascript files")
# pprint(js_files)
for js_file in js_files:
    try:
        js_file.unlink()
    except Exception as error_msg:
        logger.error(f"failed to delete '{js_file}' -> error: {error_msg}")

css_links = dom_tree.css('link[rel="stylesheet"]')
css_styles = ""
import_pattern = re.compile(r"(?m)(\@import url\(\")([^\"]+)(\"\)\;)")

for css_link in css_links:
    link_href = str(css_link.attrs["href"])
    link_path = documents_path / Path(link_href)
    logger.debug(f"validating existence of '{link_path}' ...")
    if not link_path.exists():
        logger.debug(f"removing '{css_link}' -> source file does not seem to exist")
        css_link.decompose()
    else:
        logger.debug(f"found '{link_path}' (size: {link_path.stat().st_size}) ")

        logger.debug(f"reading from '{link_path}' ...")

        css_rules = ""
        with open(link_path, "r", encoding="utf-8") as file_handle:
            css_rules = "\n" + str(file_handle.read())

        logger.debug(
            f"reading from '{link_path}' (length: {link_path.stat().st_size}) completed"
        )

        css_imports = list(re.findall(import_pattern, css_rules))
        if len(css_imports) > 0:
            for css_import in css_imports:
                import_path = static_files_path / Path(str(css_import[1]))
                if import_path.exists():
                    logger.debug(f"reading from '{import_path}' ...")

                    with open(import_path, "r", encoding="utf-8") as file_handle:
                        css_rules = f"\n{file_handle.read()}\n{css_rules}"

                    logger.debug(
                        f"reading from '{import_path}' (length: {import_path.stat().st_size}) completed"
                    )
                else:
                    logger.debug(
                        f"reading from '{import_path}' failed -> file does not seem to exist"
                    )

        css_styles += css_rules

for style_tag in dom_tree.css("style"):
    css_styles += "\n" + str(style_tag.text).strip()
    style_tag.decompose()

css_min_file = "styles.min.css"
css_min_path = static_files_path / css_min_file
last_link = dom_tree.css('link[rel="stylesheet"]')[-1]
last_link.attrs["href"] = "_static/" + css_min_file
last_link.attrs["type"] = "text/css"
if "media" in last_link.attrs:
    del last_link.attrs["media"]

css_links = dom_tree.css('link[rel="stylesheet"]')
for link_index in range(len(css_links) - 1):  # remove all other 'link' tags
    css_links[link_index].decompose()

css_styles = re.sub(
    import_pattern, "", css_styles
)  # remove obsolete imports -> after merging all files

styles_parser = css_parser.CSSParser(raiseExceptions=False)
css_sheet = styles_parser.parseString(css_styles)

remove_rules = []
removed_counter = 0
for css_rule in css_sheet:
    try:
        if hasattr(css_rule, "media"):
            remove_rules2 = []
            for css_rule2 in css_rule:
                css_select = str(css_rule2.selectorText)
                tag_matches = dom_tree.css_matches(css_select)
                if not tag_matches:
                    # print(css_select)
                    remove_rules2.append(css_rule2)

            for css_rule2 in remove_rules2:
                try:
                    css_rule.cssRules.remove(css_rule2)
                except Exception as error_msg:
                    logger.opt(exception=error_msg).error(
                        f"failed to remove css rule '{css_rule2}' -> error: {error_msg}"
                    )
                removed_counter += 1

            continue
        elif hasattr(css_rule, "selectorText"):
            css_select = str(css_rule.selectorText)
            tag_matches = dom_tree.css_matches(css_select)
            if not tag_matches:
                # print(css_select)
                remove_rules.append(css_rule)
        else:
            # print(css_rule)
            remove_rules.append(css_rule)
    except Exception as error_msg:
        logger.opt(exception=error_msg).error(
            f"processing of css rule '{css_rule}' failed -> error: {error_msg}"
        )

for css_rule in remove_rules:
    css_sheet.cssRules.remove(css_rule)

logger.debug(f"removed {removed_counter + len(remove_rules)} obsolete css rules")

old_css_len = len(css_styles)
css_styles = str(css_sheet.cssText.decode())

css_styles = str(re.sub(r"(?m)[\n\r]+", "", css_styles))
css_styles = str(re.sub(r"(?m)( ){2}", "", css_styles))

new_css_len = len(css_styles)

css_files = list(static_files_path.glob("*.css"))

logger.debug(f"found {len(css_files)} obsolete css files")
# pprint(js_files)
for css_file in css_files:
    try:
        css_file.unlink()
    except Exception as error_msg:
        logger.opt(exception=error_msg).error(
            f"failed to delete '{css_file}' -> error: {error_msg}"
        )

css_len_diff = old_css_len - new_css_len
css_len_percent = css_len_diff / old_css_len * 100
logger.debug(
    f"reduced size of css by {css_len_diff} characters (to ca. {round(css_len_percent, 1)} percent of original)"
)

# remove css comments -> not possible using css_parser
css_styles = re.sub(r"\/\*[^\*\\]+\*\/", "", css_styles)

with open(css_min_path, "w+", encoding="utf-8") as file_handle:
    file_handle.write(css_styles)

index_html = str(dom_tree.html)

logger.debug(f"writing to '{index_path}' ...")

try:
    with open(index_path, "w+", encoding="utf-8") as file_handle:
        file_handle.write(
            htmlmin.minify(index_html, remove_empty_space=True, remove_comments=True)
        )
except Exception as error_msg:
    logger.opt(exception=error_msg).error(
        f"minification of '{index_path}' failed -> error: {error_msg}"
    )
    with open(index_path, "w+", encoding="utf-8") as file_handle:
        file_handle.write(index_html)

index_new_size = index_path.stat().st_size
index_len_diff = index_old_size - index_new_size

logger.debug(
    f"writing to '{index_path}' completed -> reduced size by {index_len_diff} bytes"
)

# TODO: convert images to modern formats
img_files = (
    list(static_files_path.glob("*.png"))
    + list(static_files_path.glob("*.jpg"))
    + list(static_files_path.glob("*.svg"))
)

logger.debug(
    f"found {len(img_files)} images (.png, .jpg, .svg) in '{static_files_path}'"
)

for img_file in img_files:
    try:
        file_name = str(img_file.stem + img_file.suffix)
        if file_name in index_html:
            continue
        if file_name in css_styles:
            continue
        else:
            logger.debug(
                f"removing image '{img_file}' -> file name '{file_name}' has not been found in css or html"
            )
            try:
                img_file.unlink()
            except Exception as error_msg:
                logger.opt(exception=error_msg).error(
                    f"failed to delete '{img_file}' -> error: {error_msg}"
                )
    except Exception as error_msg:
        logger.opt(exception=error_msg).error(
            f"failed to validate existence of '{img_file}' -> error: {error_msg}"
        )

# delete now obsolete files
unzip_path = zip_file.parent / zip_file.stem
shutil.rmtree(unzip_path)
zip_file.unlink()

sys.exit(0)

meta_path = docset_path / "meta.json"

# FIXME: search and fix bug
if not meta_path.exists():
    logger.debug(f"preparing contents of '{meta_path}' ... ")

    requests_version = "2.31.0"

    meta_json = {
        "feed_url": "https://zealusercontributions.vercel.app/api/docsets/Requests.xml",
        "name": "Requests",
        "title": "Requests",
        "urls": [
            "https://kapeli.com/feeds/zzz/user_contributed/build/Requests/Requests.tgz",
            "https://sanfrancisco.kapeli.com/feeds/zzz/user_contributed/build/Requests/Requests.tgz",
            "https://newyork.kapeli.com/feeds/zzz/user_contributed/build/Requests/Requests.tgz",
            "https://london.kapeli.com/feeds/zzz/user_contributed/build/Requests/Requests.tgz",
            "https://frankfurt.kapeli.com/feeds/zzz/user_contributed/build/Requests/Requests.tgz",
        ],
        "version": requests_version,
    }

    with open(meta_path, "w+", encoding="utf-8") as file_handle:
        file_handle.write(json.dumps(meta_json))

    logger.debug(f"wrote contents of '{meta_path}' ")
