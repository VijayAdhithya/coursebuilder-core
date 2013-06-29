# Copyright 2013 Google Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS-IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Classes supporting creation and editing of questions."""

__author__ = 'John Orr (jorr@google.com)'


import cgi
import urllib
from common import schema_fields
from controllers.utils import ApplicationHandler
from controllers.utils import BaseRESTHandler
from controllers.utils import XsrfTokenManager
from models import transforms
from models.models import QuestionDAO
from models.models import QuestionDTO
from modules.oeditor import oeditor
import messages
from unit_lesson_editor import CourseOutlineRights


class BaseDatastoreAssetEditor(ApplicationHandler):
    def get_form(self, rest_handler, key=''):
        """Build the Jinja template for adding a question."""
        rest_url = self.canonicalize_url(rest_handler.URI)
        exit_url = self.canonicalize_url('/dashboard?action=assets')
        if key:
            delete_url = '%s?%s' % (
                self.canonicalize_url(rest_handler.URI),
                urllib.urlencode({
                    'key': key,
                    'xsrf_token': cgi.escape(
                        self.create_xsrf_token(rest_handler.XSRF_TOKEN))
                    }))
        else:
            delete_url = None

        schema = rest_handler.get_schema()

        return oeditor.ObjectEditor.get_html_for(
            self,
            schema.get_json_schema(),
            schema.get_schema_dict(),
            key, rest_url, exit_url,
            delete_url=delete_url, delete_method='delete',
            required_modules=rest_handler.REQUIRED_MODULES)


class QuestionManagerAndEditor(BaseDatastoreAssetEditor):
    """An editor for editing and managing questions."""

    def prepare_template(self, rest_handler, key=''):
        """Build the Jinja template for adding a question."""
        template_values = {}
        template_values['page_title'] = self.format_title('Edit Question')
        template_values['main_content'] = self.get_form(rest_handler, key=key)

        return template_values

    def get_add_mc_question(self):
        self.render_page(self.prepare_template(McQuestionRESTHandler))

    def get_add_sa_question(self):
        self.render_page(self.prepare_template(SaQuestionRESTHandler))

    def get_edit_question(self):
        key = self.request.get('key')
        question = QuestionDAO.load(key)

        if not question:
            raise Exception('No question found')

        if question.type == QuestionDTO.MULTIPLE_CHOICE:
            self.render_page(
                self.prepare_template(McQuestionRESTHandler, key=key))
        elif question.type == QuestionDTO.SHORT_ANSWER:
            self.render_page(
                self.prepare_template(SaQuestionRESTHandler, key=key))
        else:
            raise Exception('Unknown question type: %s' % question.type)


class BaseQuestionRESTHandler(BaseRESTHandler):
    """Common methods for handling REST end points with questions."""

    def put(self):
        """Store a question in the datastore in response to a PUT."""
        request = transforms.loads(self.request.get('request'))
        key = request.get('key')

        if not self.assert_xsrf_token_or_fail(
                request, self.XSRF_TOKEN, {'key': key}):
            return

        if not CourseOutlineRights.can_edit(self):
            transforms.send_json_response(
                self, 401, 'Access denied.', {'key': key})
            return

        payload = request.get('payload')
        question_dict = transforms.loads(payload)

        if key:
            question = QuestionDTO(key, question_dict)
        else:
            question = QuestionDTO(None, question_dict)
            question.type = self.TYPE

        QuestionDAO.save(question)

        transforms.send_json_response(self, 200, 'Saved.')

    def delete(self):
        """Remove a question from the datastore in response to DELETE."""
        key = self.request.get('key')

        if not self.assert_xsrf_token_or_fail(
                self.request, self.XSRF_TOKEN, {'key': key}):
            return

        if not CourseOutlineRights.can_delete(self):
            transforms.send_json_response(
                self, 401, 'Access denied.', {'key': key})
            return

        question = QuestionDAO.load(key)
        if not question:
            transforms.send_json_response(
                self, 404, 'Question not found.', {'key': key})
            return
        question.delete()
        transforms.send_json_response(self, 200, 'Deleted.')


class McQuestionRESTHandler(BaseQuestionRESTHandler):
    """REST handler for editing multiple choice questions."""

    URI = '/rest/question/mc'

    REQUIRED_MODULES = [
        'gcb-rte', 'inputex-select', 'inputex-string', 'inputex-list']

    TYPE = QuestionDTO.MULTIPLE_CHOICE
    XSRF_TOKEN = 'mc-question-edit'

    @classmethod
    def get_schema(cls):
        """Get the InputEx schema for the multiple choice question editor."""
        mc_question = schema_fields.FieldRegistry(
            'Multiple Choice Question',
            description='multiple choice question',
            extra_schema_dict_values={'className': 'mc-container'})

        mc_question.add_property(schema_fields.SchemaField(
            'question', 'Question', 'html', optional=True,
            extra_schema_dict_values={'className': 'mc-question'}))
        mc_question.add_property(schema_fields.SchemaField(
            'description', 'Description', 'string', optional=True,
            description=messages.QUESTION_DESCRIPTION))

        choice_type = schema_fields.FieldRegistry(
            'Choice',
            extra_schema_dict_values={'className': 'mc-choice'})
        choice_type.add_property(schema_fields.SchemaField(
            'score', 'Score', 'string', optional=True,
            extra_schema_dict_values={'className': 'mc-choice-score'}))
        choice_type.add_property(schema_fields.SchemaField(
            'text', 'Text', 'html', optional=True,
            extra_schema_dict_values={'className': 'mc-choice-text'}))
        choice_type.add_property(schema_fields.SchemaField(
            'feedback', 'Feedback', 'html', optional=True,
            extra_schema_dict_values={'className': 'mc-choice-feedback'}))

        choices_array = schema_fields.FieldArray(
            'choices', '', item_type=choice_type,
            extra_schema_dict_values={
                'className': 'mc-choice-container',
                'listAddLabel': 'Add a choice',
                'listRemoveLabel': 'Delete choice'})

        mc_question.add_property(choices_array)

        return mc_question

    def get(self):
        """Get the data to populate the question editor form."""
        key = self.request.get('key')

        if not CourseOutlineRights.can_view(self):
            transforms.send_json_response(
                self, 401, 'Access denied.', {'key': key})
            return

        if key:
            question = QuestionDAO.load(key)
            payload_dict = question.dict
        else:
            payload_dict = {
                'question': '',
                'description': '',
                'choices': [
                    {'score': '', 'text': '', 'feedback': ''},
                    {'score': '', 'text': '', 'feedback': ''}
                ]}

        transforms.send_json_response(
            self, 200, 'Success',
            payload_dict=payload_dict,
            xsrf_token=XsrfTokenManager.create_xsrf_token(self.XSRF_TOKEN))


class SaQuestionRESTHandler(BaseQuestionRESTHandler):
    """REST handler for editing short answer questions."""

    URI = '/rest/question/sa'

    REQUIRED_MODULES = [
        'gcb-rte', 'inputex-select', 'inputex-string', 'inputex-list']

    TYPE = QuestionDTO.SHORT_ANSWER
    XSRF_TOKEN = 'sa-question-edit'

    @classmethod
    def get_schema(cls):
        """Get the InputEx schema for the short answer question editor."""
        sa_question = schema_fields.FieldRegistry(
            'Short Answer Question',
            description='short answer question',
            extra_schema_dict_values={'className': 'mc-container'})

        sa_question.add_property(schema_fields.SchemaField(
            'question', 'Question', 'html', optional=True,
            extra_schema_dict_values={'className': 'mc-question'}))
        sa_question.add_property(schema_fields.SchemaField(
            'description', 'Description', 'string', optional=True,
            description=messages.QUESTION_DESCRIPTION))

        grader_type = schema_fields.FieldRegistry(
            'Grader',
            extra_schema_dict_values={'className': 'mc-choice'})
        grader_type.add_property(schema_fields.SchemaField(
            'score', 'Score', 'string', optional=True,
            extra_schema_dict_values={'className': 'mc-choice-score'}))
        grader_type.add_property(schema_fields.SchemaField(
            'matcher', 'Grading', 'select', optional=True,
            select_data=[
                ('case_insensitive', 'Case insensitive string match'),
                ('regex', 'Regular expression'),
                ('hnumeric', 'Numeric')],
            extra_schema_dict_values={'className': 'mc-choice-score'}))
        grader_type.add_property(schema_fields.SchemaField(
            'response', 'Response', 'string', optional=True,
            extra_schema_dict_values={'className': 'mc-choice-text'}))
        grader_type.add_property(schema_fields.SchemaField(
            'feedback', 'Feedback', 'html', optional=True,
            extra_schema_dict_values={'className': 'mc-choice-feedback'}))

        graders_array = schema_fields.FieldArray(
            'choices', '', item_type=grader_type,
            extra_schema_dict_values={
                'className': 'mc-choice-container',
                'listAddLabel': 'Add a response',
                'listRemoveLabel': 'Delete response'})

        sa_question.add_property(graders_array)

        return sa_question

    def get(self):
        """Get the data to populate the question editor form."""
        key = self.request.get('key')

        if not CourseOutlineRights.can_view(self):
            transforms.send_json_response(
                self, 401, 'Access denied.', {'key': key})
            return

        if key:
            question = QuestionDAO.load(key)
            payload_dict = question.dict
        else:
            payload_dict = {
                'question': '',
                'description': '',
                'choices': [
                    {
                        'score': '1.0',
                        'matcher': 'case_insensitive',
                        'response': '',
                        'feedback': ''}]}

        transforms.send_json_response(
            self, 200, 'Success',
            payload_dict=payload_dict,
            xsrf_token=XsrfTokenManager.create_xsrf_token(self.XSRF_TOKEN))