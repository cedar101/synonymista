#!/usr/bin/env python
# -*- encoding: utf-8 -*-
import sys
# import logging
# import pickle
# from functools import partial
# from contextlib import suppress
# Simport json
from collections import NamedTuple

from flask import Flask, Response, render_template, redirect, url_for, request, flash, session, send_file
from flask_debugtoolbar import DebugToolbarExtension
from flask_bootstrap import Bootstrap
from flask_pony import Pony
from flask_wtf import FlaskForm
#from flask_wtf.csrf import CSRFProtect

from wtforms import validators, SubmitField, StringField, SelectMultipleField
# from wtforms_components import SelectMultipleField
from wtforms.widgets import html_params, HtmlString #, CheckboxInput, ListWidget, TableWidget
#from wtforms.fields import Field

import click

from pony.orm import db_session, commit, select, delete, sql_debug, Set, Optional, Required
from pony.orm.serialization import to_dict

from gensim.models.keyedvectors import KeyedVectors

from logging import getLogger
from logbook import Logger, StreamHandler
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


app.config.update({
    # 'KONCH_SHELL': 'ptpython',
    'KONCH_CONTEXT': {k: v for k, v in globals().items()
                      if k in 'db db_session select Word WordSimlarity'.split()}
})


@app.cli.command()
def initdb():
    """Initialize the database."""
    click.confirm('Initing the db! Do you want to continue?', abort=True)
    # db.drop_table('word', if_exists=True, with_all_data=True)
    # db.drop_table('word_similarity', if_exists=True, with_all_data=True)
    db.generate_mapping(create_tables=True)
    click.echo('Inited the db.')


@db_session
def get_selected_words(word_value):
    # word = Word.get(value=word_value)
    # word_smilarity_dict = word.to_dict(related_objects=True, with_collections=True)
    word_similarites = select((wordsim.similar_word.value, wordsim.value)
                              for word in Word
                              for wordsim in word.similar_to
                              if word.value == word_value)
    return word_similarites[:] if word_similarites else []


@db_session
def save_selected_words(word_value, selected_data):
    delete(wsim for w in Word for wsim in w.similar_to if w.value == word_value)
    word = Word.get_or_create(value=word_value)
    word.similar_to = [WordSimilarity.get_or_create(
                                        value=sim,
                                        similar_word=Word.get_or_create(value=w)
                                      )
                       for w, sim in selected_data]

DescriptionLabelFieldData = namedtuple('DescriptionLabelFieldData',
                                       'value label description')
WordSimilarityData = namedtuple('WordSimilarityData', 'word similarity')


def get_similar_words(word, topn=10):
    #return app.word_model.most_similar(word, topn=top_n)
    return [DescriptionLabelFieldData(value=WordSimilarityData(word, similarity),
                                      label=word, description=similarity)
            for word, similarity in app.word_model.most_similar(word, topn=topn)]


def coerce_word_similarity(s):
    # import pdb; pdb.set_trace()
    # log = getLogger('coerce')
    # log.debug(s)
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
        yield '<table {}>'.format(html_params(id=field_id,
                                              class_=self.table_class))
        yield (f'<thead><th>{self.col0header}</th><th>{self.col1header}</th>'
               f'<th class="col-md-1">{self.col2header}</th></thead>'
               '<tbody>')
        for value, label, checked in self.field.iter_choices():
            choice_id = f'{field_id}-{label}'
            options = dict(self.kwargs,
                           style="height:auto;",
                           name=self.field.name, value=value, id=choice_id)
            if checked:
                options['checked'] = 'checked'
            link_url = url_for('index', word=label)
            word, similarity = coerce_word_similarity(value)    # XXX
            yield (f'<tr><td><label for="{field_id}"><a= href="{link_url}">{label}</a></label></td>'
                   f'<td>{similarity}</td>'
                   '<td><input {} /></td></tr>').format(html_params(**options))
        yield '</tbody></table>'

    def __call__(self, field, **kwargs):
        self.field = field
        self.kwargs = kwargs
        return ''.join(self)


class DescriptionLabelTableWidget(object):
    """
    Renders a list of fields as a set of table rows with th/td pairs.

    If `with_table_tag` is True, then an enclosing <table> is placed around the
    rows.
    """
    def __init__(self, with_table_tag=True):
        self.with_table_tag = with_table_tag

    def __iter__(self):
        if self.with_table_tag:
            kwargs.setdefault('id', field.id)
            yield '<table {}>'.format(html_params(**kwargs))
        for subfield in field:
            yield (f'<tr><th>{subfield.label}</th>'
                   f'<td>{subfield.description}</td>'
                   f'<td>{subfield}</td></tr>')
            yield '</table>'

    def __call__(self, field, **kwargs):
        self.field = field
        self.kwargs = kwargs
        return HTMLString(''.join(self))

# class WordSimilarityField(SelectMultipleField):
#     """(word, similarity) 튜플 리스트"""
#     def _value(self):
#         if self.data:
#             return u', '.join(self.data)
#         else:
#             return u''
#
#     def process_formdata(self, valuelist):
#         if valuelist:
#             self.data = [x.strip() for x in valuelist[0].split(',')]
#         else:
#             self.data = []

# class SelectMultipleFieldWOPreValidate(SelectMultipleField):
#     """docstring for SelectMultipleFieldWOPreValidate."""
#     def pre_validate(self, form):
#         return None

# class WordSimilarityForm(FlaskForm):
#     similar_word = StringField('Similar Words')
#     similarity = StringField('Similarity')
#     #is_synonym
#
# class MultiCheckboxField(SelectMultipleField):
#     widget = widgets.TableWidget()
#     option_widget = widgets.CheckboxInput()


class DescriptionLabelSelectField(SelectBaseField):
    def iter_choices(self):
        for value, label, description in self.choices:
            selected = self.data is not None and self.coerce(value) in self.data
            yield (value, label, description, selected)

    def __iter__(self):
        opts = {'widget':self.option_widget,
                '_name':self.name, '_form':None, '_meta':self.meta}
        for i, (value, label, description, checked) in enumerate(self.iter_choices()):
            opt = self._Option(label=label, id=f'{self.id}-{i}', **opts)
            opt.process(None, value)
            opt.checked = checked
            opt.description = description
            yield opt


class DescriptionLabelSelectMultipleField(SelectMultipleField, DescriptionLabelSelectField):
    widget = ExtraLabelTableWidget()
    option_widget = widgets.CheckboxInput()
    # def __init__(self, extra_data=None, **kwargss):
    #     super(ExtraLabelField, self).__init__(**kwargs)
    #     self.extra_data = extra_data

    def __init__(self, label=None, validators=None, coerce=str,
                 coerce_extra=str, choices=None, **kwargs):
        super().__init__(label, validators, coerce, choices, **kwargs)

    # def process_data(self, value):
    #     """
    #     Process the Python data applied to this field and store the result.
    #
    #     This will be called during form construction by the form's `kwargs` or
    #     `obj` argument.
    #
    #     :param value: The python object containing the value to process.
    #     """
    #     try:
    #         self.data = [self.coerce(v) for v in value]
    #     except (ValueError, TypeError):
    #         self.data = None
    #
    # def process_formdata(self, valuelist):
    #     """
    #     Process data received over the wire from a form.
    #
    #     This will be called during form construction with data supplied
    #     through the `formdata` argument.
    #
    #     :param valuelist: A list of strings to process.a
    #     """
    #     try:
    #         self.data = [self.coerce(x) for x in valuelist]
    #     except ValueError:
    #         raise ValueError(self.gettext('Invalid choice(s): one or more data inputs could not be coerced'))


class WordSimilaritiesForm(FlaskForm):
    word = StringField('Word', validators=[validators.Required()])
    similar_words = SelectMultipleField( #WOPreValidate(
                        'Similar words',
                        coerce=coerce_word_similarity,
                        # validators=[validators.optional()],
                        widget=ThreeColumnCheckboxWidget(
                                'Word', 'Similarity',
                                'Synonym?',
                                'table table_condensed'
                        )
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

    word_similarity = get_selected_words(word)
    # form = WordSimilarityForm.from_json(word.to_dict())

    form = WordSimilarityForm()

    try:
        # form.similar_words.choices = partial(get_similar_words, word)
        form.similar_words.choices = get_similar_words(word) if word else []
        form.similar_words.data = word_similarity
    except KeyError as e:
        flash(str(e))
        form.similar_words.choices = []

    log.debug(f'choices = {form.similar_words.choices}')
    log.debug(f'data = {form.similar_words.data}')

    if form.submit.data and form.validate_on_submit():
        word = form.word.data
        similar_words = form.similar_words.data
        save_selected_words(word, similar_words)
        log.debug(similar_words)
        return redirect(url_for('index',
                                word=word, similar_words=similar_words))

    form.word.data = word
    form.similar_words.data = get_selected_words(word)
    log.debug(f'data = {form.similar_words.data}')

    return render_template('index.html', form=form)
                        #    word=session.get('word'),
                        #    similar_words=session.get('similar_words'))


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
# if __name__ == '__main__':
#     manager.run()
