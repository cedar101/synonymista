#!/usr/bin/env python
# -*- encoding: utf-8 -*-
import sys
# import logging
# import pickle
import functools

from flask import Flask, render_template, session, redirect, url_for, request #, flash, current_app)
# from flask_script import Manager
from flask_bootstrap import Bootstrap
from flask_wtf import FlaskForm
#from flask_wtf.csrf import CSRFProtect
from flask_pony import Pony
from wtforms import validators, StringField, SubmitField
from wtforms_components import SelectMultipleField
from wtforms.widgets import html_params #, CheckboxInput, ListWidget, TableWidget

import click

from pony.orm import Set, Required # composite_key,

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

app = Flask(__name__)
app.config.from_object(__name__)

# manager = Manager(app)
#csrf = CSRFProtect(app)
bootstrap = Bootstrap(app)
orm = Pony(app)
db = orm.get_db()
#db.sql_debug(DEBUG)

# '../models/wiki_dmpv_1000_no_taginfo_word2vec_format.bin'
word_model_filename = 'models/wiki_dmpv_100_no_taginfo_user_dic_word2vec_format.bin' # sys.argv[1]

@app.before_first_request
def setup_model(*args, **kwargs):
    app.word_model = KeyedVectors.load_word2vec_format(word_model_filename,
                                                       binary=True)


def similarites(word):
    return ((similarity, word)
            for word, similarity in app.word_model.most_similar(word, topn=10))




class Word(db.Entity):
    _table_ = 'word'
    value = Required(str, unique=True)
    similar_to = Set('WordSimilarity', reverse='word')
    similar_from = Set('WordSimilarity', reverse='similar_word')


class WordSimilarity(db.Entity):
    _table_ = 'word_similarity'
    value = Required(float)
    word = Required(Word, reverse='similar_to')
    similar_word = Required(Word, reverse='similar_from')


@app.cli.command()
def initdb():
    """Initialize the database."""
    click.echo('Init the db!')
    db.drop_table('word', if_exists=True)
    db.drop_table('word_similarity', if_exists=True)
    db.generate_mapping(create_tables=True)


def selected(word):
    selected_word = Word.get(value=word)
    return db.select((word.similar_to.similarity,
                      word.similar_to.word)
                     for w in Word
                     if w.value == selected_word)


class MulitCheckboxWidget(object):
    def __init__(self, table_class='table'):
        self.table_class = table_class

    def __iter__(self):
        '''renders a collection of checkboxes'''
        self.kwargs.setdefault('type', 'checkbox')
        field_id = self.kwargs.pop('id', self.field.id)
        yield ('<table {}>'
               '<thead><th>Word</th><th>Similarity</th>'
               '<th class="col-md-1">Synonym?</th></thead>'
               '<tbody>').format(html_params(id=field_id, class_=self.table_class))
        for value, label, checked in self.field.iter_choices():
            choice_id = f'{field_id}-{value}'
            options = dict(self.kwargs, name=self.field.name, value=value, id=choice_id)
            if checked[1]:
                options['checked'] = 'checked'
            link_url = url_for('index', word=label)
            yield (f'<tr><td><label for="{field_id}"><a href="{link_url}">{label}</a></label></td>'
                   f'<td>{value}</td>'
                   '<td><input {} /></td></tr>').format(html_params(**options))
        yield '</tbody></table>'

    def __call__(self, field, **kwargs):
        self.field = field
        self.kwargs = kwargs
        return ''.join(self)


class WordSimilarityForm(FlaskForm):
    word = StringField('Word', validators=[validators.Required()])
    #similar_words = MultiCheckboxField('Similar words', choices=choices)
    similar_words = SelectMultipleField('Similar words', coerce=float, choices=[],
                                        validators=[validators.optional()],
                                        widget=MulitCheckboxWidget('table table_condensed'))
    submit = SubmitField('Submit')




@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404


@app.errorhandler(500)
def internal_server_error(e):
    return render_template('500.html'), 500


@app.route('/', methods=['GET', 'POST'])
def index():
    form = WordSimilarityForm() #data=locals()) #{'word': word, 'similar_words': selected(word)})

    if form.validate_on_submit():
        session['word'] = word = form.word.data
        return redirect(url_for('index', word=word))

    word = form.word.data = request.args.get('word')
    form.similar_words.choices = (functools.partial(similarites, word)
                                  if word else [])
    form.similar_words.data = [] #selected(word) if form.word.data else []

    return render_template('index.html', form=form) #, word=session.get('word'))


# if __name__ == '__main__':
#     manager.run()
