from typing import List, Dict, Union
from celery import shared_task
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from weasyprint import HTML
from .models import Answer, ModelSettings
import openai
import os


@shared_task
def send_formative_feedback_email(
    email: List[str],
    questionnaire_title: str,
    feedbacks: List[Dict[str, Union[str, bool, int]]],
    correct_count_answers: int,
    student_email: str,
) -> None:
    try:
        html_string = render_to_string(
            "feedback_template.html",
            {
                "questionnaire_title": questionnaire_title,
                "feedbacks": feedbacks,
                "correct_count_answers": correct_count_answers,
                "student_email": student_email,
            },
        )
        html = HTML(string=html_string)
        pdf_file = html.write_pdf()

        email_message = EmailMessage(
            f"Feedback Formativo - {questionnaire_title}",
            f'Olá, \nEncontre em anexo o feedback relacionado ao email {student_email} referente ao questionário: "{questionnaire_title}".',
            os.getenv("EMAIL_HOST_USER", ""),
            email,
        )
        email_message.attach("formative_feedback.pdf", pdf_file, "application/pdf")
        email_message.send()

    except Exception as e:
        print(f"Error sending feedback email: {str(e)}")


@shared_task
def send_email_with_report(subject, body, recipient_emails, report_file):
    email = EmailMessage(
        subject,
        body,
        os.getenv("EMAIL_HOST_USER", ""),
        to=recipient_emails,
    )
    email.attach(
        "relatorio.xlsx",
        report_file,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    email.send()


@shared_task
def generate_formative_feedback(
    feedbacks: List[Dict[str, Union[str, bool, int]]],
    questionnaire_content: str,
    email: List[str],
    questionnaire_title: str,
    correct_count_answers: int,
    model_settings_id: str,
    student_email: str,
) -> None:
    try:
        model_settings = ModelSettings.objects.get(id=model_settings_id)
        detailed_feedbacks = generate_feedback_details(
            feedbacks, questionnaire_content, model_settings
        )

        send_formative_feedback_email.delay(
            email,
            questionnaire_title,
            detailed_feedbacks,
            correct_count_answers,
            student_email,
        )

    except Exception as e:
        print(f"Error generating formative feedback: {str(e)}")


def generate_feedback_details(
    feedbacks: List[Dict[str, Union[str, bool, int]]],
    questionnaire_content: str,
    model_settings: ModelSettings,
) -> List[Dict[str, Union[str, bool, int]]]:
    detailed_feedbacks = []

    for feedback in feedbacks:
        if (
            not (feedback["explanation"] and feedback["improve_suggestions"])
            and not feedback["correct"]
        ):
            if len(feedback["answer"]) > 1 or len(feedback["correct_answer"]) > 1:
                prompt = create_prompt(
                    feedback, questionnaire_content, model_settings.max_tokens
                )
            else:
                prompt = create_prompt_multiple_answers(
                    feedback, questionnaire_content, model_settings.max_tokens
                )

            feedback_text = generate_openai_feedback(model_settings, prompt)

            (
                feedback["explanation"],
                feedback["improve_suggestions"],
            ) = format_feedback(feedback_text)

            save_feedback_to_answer(
                feedback["answer_id"],
                feedback["explanation"],
                feedback["improve_suggestions"],
            )

        detailed_feedbacks.append(feedback)

    return detailed_feedbacks


def format_feedback(
    feedback_text: str,
) -> Dict[str, str]:
    if (
        "Explicação" in feedback_text
        and "Sugestões de Aperfeiçoamento" in feedback_text
    ):
        explanation = (
            feedback_text.split("Explicação:")[1]
            .split("Sugestões de Aperfeiçoamento:")[0]
            .strip()
        )
        suggestions = feedback_text.split("Sugestões de Aperfeiçoamento:")[1].strip()
    else:
        explanation = feedback_text
        suggestions = ""

    return explanation, suggestions


def create_prompt(
    feedback: Dict[str, Union[str, bool, int]],
    questionnaire_content: str,
    max_tokens: int,
) -> str:
    return (
        f"Questão: {feedback['question']}\n"
        f"Resposta do aluno: {feedback['answer'][0]}\n"
        f"Gabarito: {feedback['correct_answer'][0]}\n"
        f"Conteúdo do questionário: {questionnaire_content}\n"
        f"Subconteúdo da questão: {feedback['subcontent']}\n"
        "Explique por que a resposta do aluno está incorreta e qual deveria ser a resposta certa.\n"
        "Além disso, sugira o que o aluno pode estudar para melhorar nesse assunto.\n"
        "Divida sua resposta em duas seções: 'Explicação:' e 'Sugestões de Aperfeiçoamento:'.\n"
        "Responda em texto simples, sem usar qualquer formatação como negrito, itálico ou sublinhado e sem usar tópicos, como * ou -.\n"
        f"Limite sua resposta a {(max_tokens - 100) if max_tokens > 100 else max_tokens} tokens, responda sem exceder esse limite."
    )


def create_prompt_multiple_answers(
    feedback: Dict[str, Union[str, bool, int]],
    questionnaire_content: str,
    max_tokens: int,
) -> str:
    correct_answers = []

    for answer, correct in feedback["result"].items():
        if correct:
            correct_answers.append(feedback["question"])

    correct_answers = (
        ", ".join(correct_answers) if len(correct_answers) > 0 else "Nenhuma"
    )
    wrong_answers = (
        ", ".join(feedback["wrong_answers"])
        if feedback.get("wrong_answers")
        else "Nenhuma"
    )

    return (
        f"Questão: {feedback['question']}\n"
        f"Respostas do aluno:\n"
        f"- Certas: {correct_answers}\n"
        f"- Erradas: {wrong_answers}\n"
        f"Gabarito: {', '.join(feedback['correct_answer'])}\n"
        f"Conteúdo do questionário: {questionnaire_content}\n"
        f"Subconteúdo da questão: {feedback['subcontent']}\n"
        "A seguir, forneça um feedback detalhado sobre as respostas do aluno, dividido em duas seções:\n"
        "'Explicação:' Explique por que cada resposta errada está incorreta, qual deveria ser a resposta correta e mencione se há respostas corretas faltando.\n"
        "Ou seja, se o aluno escolheu uma resposta incorreta, explique por que está incorreta.\n"
        "Se o aluno escolheu parcialmente as respostas corretas, identifique quais estão corretas e quais faltam ou porque estão incorretas.\n"
        "Se o aluno escolheu apenas respostas corretas, identifique quais faltam e porque são importantes.\n"
        "'Sugestões de Aperfeiçoamento:' Sugira o que o aluno pode estudar para melhorar nesse assunto, considerando as respostas corretas e incorretas.\n"
        "Por favor, responda em texto simples, sem usar qualquer formatação como negrito, itálico ou sublinhado e sem usar tópicos, como * ou -.\n"
        f"Limite sua resposta a {(max_tokens - 50) if max_tokens > 100 else max_tokens} tokens, responda sem exceder esse limite."
    )


def generate_openai_feedback(model_settings: ModelSettings, prompt: str) -> str:
    openai.api_key = model_settings.openai_api_key

    response = openai.ChatCompletion.create(
        model=model_settings.model,
        messages=[
            {
                "role": "system",
                "content": model_settings.system_content,
            },
            {"role": "user", "content": prompt},
        ],
        max_tokens=model_settings.max_tokens,
        temperature=float(model_settings.temperature),
    )

    return response.choices[0].message["content"].strip()


def save_feedback_to_answer(
    answer_id: int, feedback_explanation: str, feedback_improve_suggestions: str
) -> None:
    answer = Answer.objects.get(id=answer_id)
    answer.feedback_explanation = feedback_explanation
    answer.feedback_improve_suggestions = feedback_improve_suggestions
    answer.save()
