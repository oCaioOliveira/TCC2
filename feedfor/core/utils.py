import os
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from weasyprint import HTML

def send_feedback_email(email, questionnaire_name, feedbacks):
    html_string = render_to_string('feedback_template.html', {'questionnaire_name': questionnaire_name, 'feedbacks': feedbacks})
    html = HTML(string=html_string)
    pdf_file = html.write_pdf()

    email_message = EmailMessage(
        f'Feedback Formativo - {questionnaire_name}',
        f'Olá, encontre em anexo o seu feedback formativo referente ao questionário "{questionnaire_name}".',
        os.getenv("EMAIL_HOST_USER", ""),
        [email]
    )
    email_message.attach('formative_feedback.pdf', pdf_file, 'application/pdf')
    email_message.send()