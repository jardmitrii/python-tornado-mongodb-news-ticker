#!/usr/bin/env python3
import uuid
import motor.motor_tornado as motor
import feedparser
import bleach
from math import ceil
from os.path import join, dirname, splitext
from datetime import datetime
from tornado.escape import url_escape
from tornado.ioloop import IOLoop
from tornado.web import RequestHandler, Application, StaticFileHandler, HTTPError
from tornado.gen import coroutine
from urllib.parse import urlparse
from urllib.request import urlretrieve
from wtforms.fields import StringField
from wtforms.validators import DataRequired
from wtforms_tornado import Form
from html.parser import HTMLParser
from elasticsearch import Elasticsearch
from config import *


class HomeHandler(RequestHandler):
    @coroutine
    def get(self):
        page = max(int(self.get_argument("page", '1')), 1)
        db = self.settings['db']
        total_pages = ceil((yield db.news.find().count()) / news_per_page)
        entries = (yield db.news.find()
                   .limit(news_per_page)
                   .skip((page - 1) * news_per_page)
                   .sort([('published', -1)])
                   .to_list(length=news_per_page)
                   )
        self.render("news.html", entries=entries, pages_list=range(1, total_pages + 1))


# This class's functionality is the same as of HomeHandler class and it's made only for async/await example
class NewsHandler(RequestHandler):
    async def get(self):
        page = max(int(self.get_argument("page", '1')), 1)
        db = self.settings['db']
        total_pages = ceil((await db.news.count()) / news_per_page)
        entries = await (db.news.find()
                         .limit(news_per_page)
                         .skip((page - 1) * news_per_page)
                         .sort([('published', -1)])
                         .to_list(length=news_per_page)
                         )
        self.render("news.html", entries=entries, pages_list=range(1, total_pages + 1))


class AddHandler(RequestHandler):
    def get(self):
        self.render("add.html", error='', languages=languages)

    @coroutine
    def post(self):
        class AddForm(Form):
            title = StringField(validators=[DataRequired()])
            msg = StringField(validators=[DataRequired()])

        form = AddForm(self.request.arguments)
        if form.validate():
            action = self.get_argument('action', None)
            if not action or action not in languages.keys():
                self.redirect("/")

            title = self.get_argument('title')
            news_id = translate(title)
            msg = clean_html(self.get_argument('msg'))
            img = self.request.files.get('img', [''])[0]
            filename = ''
            if img:
                filename = generate_filename(img['filename'])
                final_path = join(self.settings['upload_path'], filename)
                output_file = open(final_path, 'wb')
                output_file.write(img['body'])
            date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            db = self.settings['db']
            result = yield db.news.insert({'news_id': news_id,
                                           'title': title,
                                           'msg': msg,
                                           'img': filename,
                                           'published': date})
            index = '{}_{}'.format(news_collection_name, action)
            esearch = self.settings['esearch']
            esearch.index(index=index,
                          doc_type=news_collection_name,
                          body={'news_id': news_id, 'title': title, 'msg': msg, 'img': filename, 'published': date})
            self.redirect("/news/" + news_id)
        else:
            self.render("add.html", error=form.errors, languages=languages)


class SearchHandler(RequestHandler):
    def get(self):
        self.render("search.html", entries='', languages=languages)

    def post(self):
        action = self.get_argument('action', None)
        if not action or action not in languages.keys():
            self.redirect("/")
        search_query = self.get_argument('msg')
        search_set = set(search_query.split())
        esearch = self.settings['esearch']
        index = '{}_{}'.format(news_collection_name, action)
        body = {"query":{"bool": {"should": [ {"match" : { "title" : search_query }},{"match": {"msg": search_query}}]}}}
        result = esearch.search(index=index, doc_type=news_collection_name, body=body)
        entries= [ hit["_source"] for hit in result['hits']['hits'] ]
        self.render("search.html", entries=entries, languages=languages)


class NewsMoreHandler(RequestHandler):
    @coroutine
    def get(self, news_id):
        db = self.settings['db']
        entry = yield db.news.find_one({'news_id': news_id})
        if entry:
            self.render("news_more.html", entry=entry)
        else:
            raise HTTPError(404)


class ImportHandler(RequestHandler):
    def get(self):
        self.render("import.html", languages=languages)

    @coroutine
    def post(self):
        class ParseImgSrc(HTMLParser):
            def handle_starttag(self, tag, attrs):
                if tag == 'img':
                    for name, value in attrs:
                        if name == 'src':
                            self.img = value
                            return

            def getImg(self):
                return self.img

        action = self.get_argument('action', None)
        if not action or action not in languages.keys():
            self.redirect("/")

        entries = feedparser.parse(rss_links_dict[action]).entries
        db = self.settings['db']
        esearch = self.settings['esearch']
        index = '{}_{}'.format(news_collection_name, action)
        for news in entries:
            news_id = translate(news.title)
            entry = yield db.news.find_one({'news_id': news_id})
            if not entry:
                published = datetime.strptime(news.published, '%a, %d %b %Y %H:%M:%S %Z').strftime("%Y-%m-%d %H:%M:%S")
                msg = clean_html(news.summary)
                parser = ParseImgSrc()
                parser.feed(msg)
                img_url = parser.getImg()
                parser.close()
                filename = 'null'
                if img_url:
                    filename = generate_filename(img_url)
                    urlretrieve(img_url, join(self.settings['upload_path'], filename))
                result = yield db.news.insert({'news_id': news_id,
                                               'title': news.title,
                                               'msg': msg,
                                               'img': filename,
                                               'published': published})
                esearch.index(index=index,
                              doc_type=news_collection_name,
                              body={'news_id': news_id,
                                    'title': news.title,
                                    'msg': msg,
                                    'img': filename,
                                    'published': published
                                    }
                              )
        self.redirect("/news/")


def return_attrs_or_function(attr_dict):
    attrs_list = []
    for attr, values in attr_dict.items():
        if not values:
            attrs_list.append(attr)
        else:
            # if one or more values are indicated - we must treat them with function
            def filter_attr_values(name, value):
                if name in ('src', 'href'):
                    p = urlparse(value)
                    return (not p.netloc) or p.netloc in attr_dict[name]
                else:
                    return not attr_dict[name] or value in attr_dict[name]
            return filter_attr_values
    return attrs_list


def clean_html(html):
    tags = [ key for key in allowed_tags_dict.keys() ]
    attrs = {tag: return_attrs_or_function(attr_dict) for tag, attr_dict in allowed_tags_dict.items() if attr_dict}
    return bleach.clean(html, tags=tags, attributes=attrs)


def translate(text):
    str_start = u"абвгдеёжзийклмнопрстуфхцчшщъыьэюя ăâîșț"
    str_result = u"abvgdeejzijklmnoprstufhzcss_y_eua_aaist"
    str_to_delite = u'<>/\!?%:»«—.,"\''
    return url_escape(text.lower().translate(str.maketrans(str_start, str_result, str_to_delite)), plus=False)


def generate_filename(img_path):
    extension = splitext(img_path)[1]
    return str(uuid.uuid4()) + extension


def make_app(settings):
    handlers = [
        # /* for handling urls like /news/ or /news////
        (r"/*", HomeHandler),
        (r"/news/*", NewsHandler),
        (r"/news/([0-9a-z_!%-]+)/*", NewsMoreHandler),
        (r"/add/*", AddHandler),
        (r"/search/*", SearchHandler),
        (r"/import/*", ImportHandler),
        (r"/images/(.*)", StaticFileHandler, {'path':  settings['upload_path']}),
    ]
    return Application(handlers=handlers, **settings)


def create_indicies():
    esearch = Elasticsearch([{'host': elasticsearch_host, 'port': elasticsearch_port}])
    for lang, code in {'romanian': 'ro','russian': 'ru'}.items():
        index = '{}_{}'.format(news_collection_name, code)
        body = {"mappings": {news_collection_name: {"properties": {"title": {"type": "string", "analyzer": lang},
                                                                   "msg": {"type": "string", "analyzer": lang}
                                                                   }}}}
        esearch.indices.create(index=index, body=body, ignore=[400, 404])

    return esearch


def main():
    settings = {'title': site_title,
                'template_path': join(dirname(__file__), "templates"),
                'static_path': join(dirname(__file__), "static"),
                'upload_path': join(dirname(__file__), "upload"),
                'debug': True,
                'db': motor.MotorClient(mongodb_host, mongodb_port).news_ticker,
                'esearch': create_indicies()
                }
    app = make_app(settings)
    app.listen(tornado_port)
    IOLoop.current().start()


if __name__ == "__main__":
    main()
