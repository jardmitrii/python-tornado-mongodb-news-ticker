# site vars
site_title = 'Try Tornado News'
news_per_page = 20

# allowed tags in news body, with attrs and its values
allowed_tags_dict = {'p': {},
                     'b': {},
                     'i': {},
                     'strong': {},
                     'em': {},
                     'img': {'src': []},
                     'iframe': {'src': ['youtube.com', 'play.md', 'vimeo.com']}
                     }

languages = {'ru': 'russian', 'ro': 'romanian'}

rss_links_dict = {'ru': 'https://point.md/ru/rss/novosti/',
                  'ro': 'https://point.md/ro/rss/noutati/'
                 }

# connections
news_collection_name = 'news'
tornado_port = 8888
mongodb_host = 'localhost'
mongodb_port = 27017
elasticsearch_host = 'localhost'
elasticsearch_port = 9200


if __name__ == "__main__":
    print("{}'s configuration file, execution is useless".format(site_title))