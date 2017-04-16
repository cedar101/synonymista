#!/usr/bin/env python
# -*- encoding: utf-8 -*-
import sys
# import logging
# import pickle
import functools

from flask import Flask, render_template, session, redirect, url_for, request #, flash, current_app)
from flask_debugtoolbar import DebugToolbarExtension
from flask_bootstrap import Bootstrap
from flask_pony import Pony
from flask_wtf import FlaskForm
#from flask_wtf.csrf import CSRFProtect

from wtforms import validators, SubmitField, StringField #, SelectMultipleField
from wtforms_components import SelectMultipleField
from wtforms.widgets import html_params #, CheckboxInput, ListWidget, TableWidget

import click

from pony.orm import db_session, select, sql_debug, Database, Set, Required

from gensim.models.keyedvectors import KeyedVectors

from logbook import StreamHandler
from logbook.compat import redirect_logging

StreamHandler(sys.stdout).push_application()
redirect_logging()

DEBUG = True
SECRET_KEY = 'development-key'
WTF_CSRF_ENABLED = False

DB_TYPE = 'mysql'
DB_PORT = 3306
DB_HOST = 'localhost'
DB_USER = 'root'
DB_PASSWORD = 'digital'
DB_NAME = 'synonymista'
DB_CHARSET = 'utf8'

DEBUG_TB_INTERCEPT_REDIRECTS = False

app = Flask(__name__)
app.config.from_object(__name__)

# manager = Manager(app)
#csrf = CSRFProtect(app)
bootstrap = Bootstrap(app)

orm = Pony(app)
db = orm.get_db()
# db = Database()

sql_debug(DEBUG)

toolbar = DebugToolbarExtension(app)

# '../models/wiki_dmpv_1000_no_taginfo_word2vec_format.bin'
word_model_filename = 'models/wiki_dmpv_100_no_taginfo_user_dic_word2vec_format.bin' # sys.argv[1]

@app.before_first_request
def setup_model():
    app.word_model = KeyedVectors.load_word2vec_format(word_model_filename,
                                                       binary=True)


@app.before_first_request
def generate_mapping():
    db.generate_mapping()


def get_similar_words(word, top_n=10):
    #return app.word_model.most_similar(word, topn=top_n)
    return [(f'{word}={similarity}', word)
            for word, similarity in app.word_model.most_similar(word, topn=top_n)]


class Word(db.Entity):
    _table_ = 'word'
    value = Required(str, unique=True)
    similar_to = Set('WordSimilarity', reverse='subject_word')
    similar_from = Set('WordSimilarity', reverse='similar_word')


class WordSimilarity(db.Entity):
    _table_ = 'word_similarity'
    value = Required(float)
    subject_word = Required(Word, reverse='similar_to')
    similar_word = Required(Word, reverse='similar_from')


app.config.update({
   'KONCH_CONTEXT': {k: v for k, v in globals().items()
                     if k in 'db Word WordSimlarity'.split()}
})


@app.cli.command()
def initdb():
    """Initialize the database."""
    click.echo('Init the db!')
    db.drop_table('word', if_exists=True)
    db.drop_table('word_similarity', if_exists=True)
    db.generate_mapping(create_tables=True)


@db_session
def get_selected_words(word_value):
    word_similarites = select((wordsim.value, wordsim.similar_word.value) #, True)
                              for word in Word
                              for wordsim in word.similar_to
                              if word.value == word_value)[:]
    #import pdb; pdb.set_trace()
    return word_similarites


def coerce_word_similarity(s):
    # import pdb; pdb.set_trace()
    word, similarity_string = s.split('=')
    similarity = float(similarity_string)
    return word, similarity


class ThreeColumnCheckboxWidget(object):
    def __init__(self, col0header, col1header, col2header, table_class='table'):
        self.col0header = col0header
        self.col1header = col1header
        self.col2header = col2header
        self.table_class = table_class

    def __iter__(self):
        '''renders a collection of checkboxes'''
        self.kwargs.setdefault('type', 'checkbox')
        field_id = self.kwargs.pop('id', self.field.id)
        yield '<table {}>'.format(html_params(id=field_id, class_=self.table_class))
        yield (f'<thead><th>{self.col0header}</th><th>{self.col1header}</th>'
               f'<th class="col-md-1">{self.col2header}</th></thead>'
               '<tbody>')
        for value, label, checked in self.field.iter_choices():
            choice_id = f'{field_id}-{label}'
            options = dict(self.kwargs, style="height:auto;",
                           name=self.field.name, value=value, id=choice_id)
            if checked:
                options['checked'] = 'checked'
            link_url = url_for('index', word=label)
            word, similarity = coerce_word_similarity(value)    # XXX
            yield (f'<tr><td><label for="{field_id}"><a href="{link_url}">{label}</a></label></td>'
                   f'<td>{similarity}</td>'
                   '<td><input {} /></td></tr>').format(html_params(**options))
        yield '</tbody></table>'

    def __call__(self, field, **kwargs):
        self.field = field
        self.kwargs = kwargs
        return ''.join(self)




class WordSimilarityForm(FlaskForm):
    word = StringField('Word', validators=[validators.Required()])
    similar_words = SelectMultipleField('Similar words', # choices=[],
                                        coerce=coerce_word_similarity,
                                        # validators=[validators.optional()],
                                        widget=ThreeColumnCheckboxWidget(
                                                'Word', 'Similarity',
                                                'Synonym?',
                                                'table table_condensed'
                                        ))
    submit = SubmitField('Submit')


@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404


@app.errorhandler(500)
def internal_server_error(e):
    return render_template('500.html'), 500


@app.route('/', methods=['GET', 'POST'])
def index():
    form = WordSimilarityForm()
    #form.similar_words.choices = []

    if form.validate_on_submit():
        session['word'] = word = form.word.data
        session['similar_words'] = similar_words = form.similar_words.data
        return redirect(url_for('index', word=word, similar_words=similar_words))

    word = form.word.data = request.args.get('word')
    form.similar_words.choices = get_similar_words(word) if word else []
    form.similar_words.data = get_selected_words(word) if word else []

    return render_template('index.html', form=form)
                        #    word=session.get('word'),
                        #    similar_words=session.get('smilar_words'))


# if __name__ == '__main__':
#     manager.run()
