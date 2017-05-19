#!/usr/bin/env python
# -*- encoding: utf-8 -*-
import sys
import ast

from typing import NamedTuple

from flask import Flask, Response, render_template, redirect, url_for, request, flash
from flask_debugtoolbar import DebugToolbarExtension
from flask_bootstrap import Bootstrap
from flask_pony import Pony
from flask_wtf import FlaskForm
#from flask_wtf.csrf import CSRFProtect

from wtforms import widgets, validators, SubmitField, StringField, SelectMultipleField
from wtforms.fields import Field

import click

from pony.orm import db_session, select, delete, sql_debug, Set, Optional, Required
# from pony.orm.serialization import to_dict

from gensim.models.keyedvectors import KeyedVectors

from logging import getLogger
from logbook import StreamHandler
from logbook.compat import redirect_logging

StreamHandler(sys.stdout).push_application()
redirect_logging()

app = Flask(__name__)
#app.config.from_object(__name__)
app.config.from_pyfile('development.cfg')

#csrf = CSRFProtect(app)
bootstrap = Bootstrap(app)

orm = Pony(app)
db = orm.get_db()

sql_debug(app.config['DEBUG'])

toolbar = DebugToolbarExtension(app)


@app.before_first_request
def setup_model():
    app.word_model = KeyedVectors.load_word2vec_format(app.config['WORD_MODEL_FILENAME'],
                                                       binary=True)


@app.before_first_request
def generate_mapping():
    db.generate_mapping()


class GetCreateMixin():
    @classmethod
    def get_or_create(cls, **params):
        o = cls.get(**params)
        return cls(**params) if o is None else o


class Word(db.Entity, GetCreateMixin):
    _table_ = 'word'
    value = Required(str, unique=True)
    similar_to = Set('WordSimilarity', reverse='subject_word')
    similar_from = Set('WordSimilarity', reverse='similar_word')


class WordSimilarity(db.Entity, GetCreateMixin):
    _table_ = 'word_similarity'
    value = Required(float)
    subject_word = Optional(Word, reverse='similar_to')
    similar_word = Required(Word, reverse='similar_from')


class DescriptionLabelFieldData(NamedTuple):
    value: any
    label: str
    description: str


app.config.update({
    'KONCH_CONTEXT': {k: v for k, v in globals().items()
                      if k in 'db db_session select Word WordSimlarity'.split()}
})


@app.cli.command()
def initdb():
    """Initialize the database."""
    print('Initing the db....')
    if click.confirm('Do you want drop the table?'):
        db.drop_table('word', if_exists=True, with_all_data=True)
        db.drop_table('word_similarity', if_exists=True, with_all_data=True)
    db.generate_mapping(create_tables=True)
    click.echo('Inited the db.')


@db_session
def get_selected_words(word_value):
    word_similarities = select((wordsim.similar_word.value, wordsim.value)
                               for word in Word
                               for wordsim in word.similar_to
                               if word.value == word_value)
    return word_similarities[:] if word_similarities else []


@db_session
def save_selected_words(word_value, selected_data):
    delete(wsim for w in Word for wsim in w.similar_to if w.value == word_value)
    word = Word.get_or_create(value=word_value)
    word.similar_to = [WordSimilarity.get_or_create(
                                        value=sim,
                                        similar_word=Word.get_or_create(value=w)
                                      )
                       for w, sim in selected_data]


def get_similar_words(word, topn=10):
    #return app.word_model.most_similar(word, topn=top_n)
    return [DescriptionLabelFieldData(value=(word, similarity),
                                      label=word, description=similarity)
            for word, similarity in app.word_model.most_similar(word, topn=topn)]

def coerce_word_similarity_data(s):
    return tuple(s if isinstance(s, tuple) else ast.literal_eval(str(s)))

class DescriptionLabelTableWidget(object):
    """
    Renders a list of fields as a set of table rows with th/td pairs.

    If `with_table_tag` is True, then an enclosing <table> is placed around the
    rows.
    """
    def __init__(self, with_table_tag=True, table_class='table table-condensed',
                 header=None, get_link_url=None):
        self.with_table_tag = with_table_tag
        self.table_class = table_class
        self.header = header
        self.get_link_url = get_link_url

    def __iter__(self):
        if self.with_table_tag:
            self.kwargs.setdefault('id', self.field.id)
            self.kwargs['class'] = self.table_class
            yield '<table {}>'.format(widgets.html_params(**self.kwargs))
        if self.header:
            yield (f'<thead><th>{self.header[0]}</th><th>{self.header[1]}</th>'
                   f'<th class="col-md-1">{self.header[2]}</th></thead>')
        yield '<tbody>'
        for subfield in self.field:
            label_text = subfield.label.text
            link_url = self.get_link_url(label_text)
            subfield.label.text = f'<a href="{link_url}">{label_text}</a>'
            yield (f'<tr><td>{subfield.label}</td>'
                   f'<td>{subfield.description}</td>'
                   f'<td class="col-md-1">{subfield}</td></tr>')
        yield '</tbody></table>'

    def __call__(self, field, **kwargs):
        self.field = field
        self.kwargs = kwargs
        return ''.join(self)


class DescriptionLabelSelectMultipleField(SelectMultipleField):
    widget = DescriptionLabelTableWidget(
        header=('Similar word', 'Similarity', 'Synonym?'),
        get_link_url=lambda similar_word: url_for('index', word=similar_word))
    option_widget = widgets.CheckboxInput()

    class _Option(Field):
        checked = False

        def _value(self):
            return str(tuple(self.data))

    def pre_validate(self, form):
        pass

    def iter_choices(self):
        for value, label, description in self.choices:
            selected = (self.data and
                        self.coerce(value)[0] in
                          [word for word, similarity in self.data])
            yield (value, label, description, selected)

    def __iter__(self):
        opts = {'widget': self.option_widget,
                '_name': self.name, '_form': None, '_meta': self.meta}
        for i, (value, label, description, checked) in enumerate(self.iter_choices()):
            opt = self._Option(label=label, id=f'{self.id}-{i}', **opts)
            opt.process(None, value)
            opt.checked = checked
            opt.description = description
            yield opt


class WordSimilaritiesForm(FlaskForm):
    word = StringField('Word', validators=[validators.Required()])
    similar_words = DescriptionLabelSelectMultipleField(
                        'Similar words',
                        coerce=coerce_word_similarity_data,
                    )
    submit = SubmitField('Submit')


@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404


@app.errorhandler(500)
def internal_server_error(e):
    return render_template('500.html'), 500


@app.route('/', methods=['GET', 'POST'])
def index():
    log = getLogger('index')
    word = request.args.get('word')
    similar_words = request.args.get('similar_words')

    form = WordSimilaritiesForm()

    if form.submit.data and form.validate_on_submit():
        word = form.word.data

        log.debug(f'data = {form.similar_words.data}')
        similar_words = form.similar_words.data
        # import pdb; pdb.set_trace()
        save_selected_words(word, similar_words)
        log.debug(similar_words)
        return redirect(url_for('index',
                                word=word, similar_words=similar_words))

    form.word.data = word
    try:
        # form.similar_words.choices = partial(get_similar_words, word)
        form.similar_words.choices = get_similar_words(word) if word else []
    except KeyError as e:
        flash(str(e))
        form.similar_words.choices = []
    form.similar_words.data = get_selected_words(word)
    log.debug(f'data = {form.similar_words.data}')
    return render_template('index.html', form=form)


@app.route('/download-all', methods=['GET', 'POST'])
def download_all():
    with db_session:
        content = str(select((w, w.value, wsim, wsim.value, wsw.value)
                             for w in Word
                             for wsim in w.similar_to
                             for wsw in wsim.similar_word)[:])
    return Response(content,
                    mimetype='text/plain',
                    headers={'Content-Disposition':
                             'attachment;filename=words.pydump'})
