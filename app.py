from flask import Flask, render_template, request, jsonify, session
from werkzeug.utils import secure_filename
import os
from dotenv import load_dotenv
import PyPDF2
import docx
import requests
from openai import OpenAI
import logging
import uuid
from validators import url as validate_url
import tiktoken
from urllib.parse import urlparse
import ipaddress
import socket
from newspaper import Article
import pytesseract
from PIL import Image
import pdf2image
from bs4 import BeautifulSoup
import ebooklib

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'your-secret-key')

# initialize openai client
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

# configure application
app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024  # 32 MB upload limit
ALLOWED_EXTENSIONS = {'txt', 'pdf', 'docx', 'rtf', 'odt', 'epub'}

#configure logging
logging.basicConfig(level=logging.INFO)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def extract_text_from_file(filepath, filename):
    text = ''
    try:
        if filename.endswith('.txt'):
            with open(filepath, 'r', encoding='utf-8') as f:
                text = f.read()
        elif filename.endswith('.pdf'):
            try:
                with open(filepath, 'rb') as f:
                    reader = PyPDF2.PdfReader(f)
                    for page in reader.pages:
                        page_text = page.extract_text()
                        if page_text:
                            text += page_text
            except:
                # use ocr for scanned pdfs
                images = pdf2image.convert_from_path(filepath)
                for image in images:
                    text += pytesseract.image_to_string(image)
        elif filename.endswith('.docx'):
            doc = docx.Document(filepath)
            text = '\n'.join([para.text for para in doc.paragraphs])
        elif filename.endswith('.rtf'):
            import striprtf
            with open(filepath, 'r', encoding='utf-8') as f:
                rtf_content = f.read()
            text = striprtf.rtf_to_text(rtf_content)
        elif filename.endswith('.odt'):
            from odf import text as odf_text
            from odf import teletype
            from odf.opendocument import load
            odt_doc = load(filepath)
            all_paras = odt_doc.getElementsByType(odf_text.P)
            text = '\n'.join([teletype.extractText(p) for p in all_paras])
        elif filename.endswith('.epub'):
            from ebooklib import epub
            book = epub.read_epub(filepath)
            text_items = []
            for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
                content = item.get_content()
                soup = BeautifulSoup(content, 'html.parser')
                text_items.append(soup.get_text())
            text = '\n'.join(text_items)
        else:
            raise ValueError('Unsupported file type')
    except Exception as e:
        logging.error(f'Error extracting text from file: {e}')
        raise
    return text

def is_safe_url(url):
    try:
        parsed_url = urlparse(url)
        hostname = parsed_url.hostname
        ip = socket.gethostbyname(hostname)
        ip_obj = ipaddress.ip_address(ip)
        if ip_obj.is_private or ip_obj.is_loopback:
            return False
        return True
    except Exception as e:
        logging.error(f'Error validating URL: {e}')
        return False

def split_text(text, max_tokens=2000):
    try:
        encoding = tiktoken.encoding_for_model('gpt-4o-mini')
    except KeyError:
        encoding = tiktoken.get_encoding('cl100k_base')
    tokens = encoding.encode(text)
    chunks = []

    for i in range(0, len(tokens), max_tokens):
        chunk_tokens = tokens[i:i + max_tokens]
        chunk_text = encoding.decode(chunk_tokens)
        chunks.append(chunk_text)

    return chunks


def calculate_total_tokens(messages, model='gpt-4o-mini'):
    encoding = tiktoken.encoding_for_model(model)
    total_tokens = 0
    for message in messages:
        content = message.get('content', '')
        total_tokens += len(encoding.encode(content))
    return total_tokens

def compress_history(conversation_history, model='gpt-4o-mini'):
    if len(conversation_history) <= 4:
        return conversation_history
    else:
        messages_to_summarize = conversation_history[4:-2]
        content_to_summarize = ' '.join([msg['content'] for msg in messages_to_summarize if msg['role'] == 'user'])
        summary_prompt = [
            {"role": "system", "content": "You are summarizing the previous conversation to maintain context."},
            {"role": "user", "content": f"Summarize the following conversation briefly: {content_to_summarize}"}
        ]
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=summary_prompt,
            max_tokens=150,
            temperature=0.3,
        )
        summary = response.choices[0].message.content.strip()
        compressed_history = conversation_history[:4] + [{"role": "assistant", "content": f"Summary of previous conversation: {summary}"}] + conversation_history[-2:]
        return compressed_history

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/summarize', methods=['POST'])
def summarize():
    data = request.form
    mode = data.get('mode')
    summary_type = data.get('summary_type')
    model_choice = data.get('model', 'gpt-4o-mini')
    file = None
    extracted_text = ''

    #handle different input modes
    if mode == 'text':
        text = data.get('text', '').strip()
        if not text:
            return jsonify({'error': 'Please provide text for summarization.'}), 400
        extracted_text = text
    elif mode == 'file':
        file = request.files.get('file')
        if not file or not allowed_file(file.filename):
            return jsonify({'error': 'Please upload a valid file.'}), 400
        filename = secure_filename(file.filename)
        filepath = os.path.join('uploads', filename)
        file.save(filepath)
        try:
            extracted_text = extract_text_from_file(filepath, filename)
        except Exception as e:
            os.remove(filepath)
            logging.error(f'Failed to process the uploaded file: {e}')
            return jsonify({'error': 'Failed to process the uploaded file.'}), 400
        os.remove(filepath)
    elif mode == 'url':
        url = data.get('url', '').strip()
        if not validate_url(url) or not is_safe_url(url):
            return jsonify({'error': 'Invalid or unsafe URL provided.'}), 400
        try:
            article = Article(url)
            article.download()
            article.parse()
            extracted_text = article.text
        except Exception as e:
            logging.error(f'Failed to fetch or parse URL: {e}')
            return jsonify({'error': 'Failed to fetch or parse URL'}), 400
    else:
        return jsonify({'error': 'Invalid input mode selected.'}), 400

    #generate a unique conversation ID
    conversation_id = str(uuid.uuid4())
    session['conversation_id'] = conversation_id

    #generate the summary
    try:
        summary = summarize_text(extracted_text, summary_type, model_choice)
    except Exception as e:
        logging.error(f'Error during summarization: {e}')
        return jsonify({'error': f'Error during summarization: {str(e)}'}), 500

    # initialize conversation history with summary + prompt
    conversation_history = [
        {"role": "system", "content": f"You are an AI assistant with expertise in summarization and detailed explanations. You provide {summary_type.replace('_', ' ')} of texts and engage in informative conversations."},
        {"role": "assistant", "content": summary},
        {"role": "assistant", "content": "Is there anything I can help you with regarding the material?"}
    ]
    session['conversation_history'] = conversation_history
    session['model_choice'] = model_choice

    return jsonify({'summary': summary, 'conversation_id': conversation_id})

def summarize_text(text, summary_type, model_choice):
    #enhance persona based on summary type
    if summary_type == 'brief':
        persona = (
            "You are an expert summarizer specializing in creating concise and succinct summaries. "
            "You focus on the most important points and communicate them clearly and efficiently."
        )
    elif summary_type == 'detailed':
        persona = (
            "You are an expert summarizer specializing in creating detailed and comprehensive summaries. "
            "You cover all significant points and provide in-depth explanations."
        )
    elif summary_type == 'key_points':
        persona = (
            "You are an expert summarizer specializing in extracting key points and presenting them as bullet lists. "
            "Each point is clear and starts with a dash (-)."
        )
    else:
        persona = (
            "You are an expert summarizer specializing in creating clear summaries. "
            "You adapt your summary to the user's needs."
        )

    #determine max tokens based on model
    if model_choice == 'gpt-4o':
        max_chunk_tokens = 8000
        max_response_tokens = 1000
    elif model_choice == 'gpt-4-turbo':
        max_chunk_tokens = 4000
        max_response_tokens = 1000
    else:  # 'gpt-4o-mini'
        max_chunk_tokens = 2000
        max_response_tokens = 500

    #split text into chunks
    chunks = split_text(text, max_tokens=max_chunk_tokens)

    # summarize each chunk
    chunk_summaries = []
    for i, chunk in enumerate(chunks):
        try:
            #construct the user prompt based on summary type
            if summary_type == 'brief':
                user_prompt = f"Please provide a brief summary of the following text in one or two sentences:\n\n{chunk}"
            elif summary_type == 'detailed':
                user_prompt = f"Please provide a detailed and comprehensive summary of the following text, covering all important points:\n\n{chunk}"
            elif summary_type == 'key_points':
                user_prompt = f"Please extract the key points from the following text and present them as a bullet-point list. Ensure each point starts on a new line with a dash (-):\n\n{chunk}"
            else:
                user_prompt = f"Please summarize the following text:\n\n{chunk}"

            messages = [
                {"role": "system", "content": persona},
                {"role": "user", "content": user_prompt}
            ]

            #initial summarization
            response = client.chat.completions.create(
                model=model_choice,
                messages=messages,
                max_tokens=max_response_tokens,
                temperature=0.3,
            )
            summary = response.choices[0].message.content.strip()

            #iterative refinement
            refinement_prompt = (
                f"Please review the following summary for clarity and completeness, and improve it if necessary. "
                f"Ensure the summary is coherent and captures the essence of the text.\n\nSummary:\n{summary}"
            )
            if summary_type == 'key_points':
                refinement_prompt += "\nEnsure each bullet point starts on a new line with a dash (-)."

            #prepare messages for refinement
            refinement_messages = [
                {"role": "system", "content": persona},
                {"role": "user", "content": refinement_prompt}
            ]

            refined_response = client.chat.completions.create(
                model=model_choice,
                messages=refinement_messages,
                max_tokens=max_response_tokens,
                temperature=0.3,
            )
            refined_summary = refined_response.choices[0].message.content.strip()

            chunk_summaries.append(refined_summary)
        except Exception as e:
            logging.error(f'Error summarizing chunk {i}: {e}')
            continue  #skip this chunk and continue with the next

    if not chunk_summaries:
        raise Exception("Failed to summarize the text.")

    #combine chunk summaries
    combined_summary = "\n\n".join(chunk_summaries)

    #final summary of summaries
    final_prompt = (
        f"Based on the following summaries, please provide a comprehensive {summary_type.replace('_', ' ')} of the entire text.\n\n"
        f"Summaries:\n{combined_summary}"
    )

    #for 'key_points', emphasize bullet points with new lines
    if summary_type == 'key_points':
        final_prompt += "\n\nPresent the final summary as a bullet-point list, ensuring each point starts on a new line with a dash (-)."

    final_messages = [
        {"role": "system", "content": persona},
        {"role": "user", "content": final_prompt}
    ]

    final_response = client.chat.completions.create(
        model=model_choice,
        messages=final_messages,
        max_tokens=max_response_tokens,
        temperature=0.3,
    )
    final_summary = final_response.choices[0].message.content.strip()

    return final_summary


@app.route('/chat', methods=['POST'])
def chat():
    data = request.get_json()
    message = data.get('message')
    conversation_type = data.get('conversation_type', 'Concise Explanation')
    conversation_id = session.get('conversation_id')
    conversation_history = session.get('conversation_history', [])
    model_choice = session.get('model_choice', 'gpt-4o-mini')

    if not message or not conversation_id:
        return jsonify({'error': 'Invalid request'}), 400

    #append the user's message to the conversation history
    conversation_history.append({"role": "user", "content": message})

    try:
        #adjust assistant's behavior based on conversation type
        if conversation_type == 'Bullet Points':
            assistant_style = (
                "As an AI assistant, provide your response in bullet points, listing key information. "
                "Ensure each point starts on a new line with a dash (-)."
            )
        elif conversation_type == 'Concise Explanation':
            assistant_style = (
                "As an AI assistant, provide a concise and clear explanation, focusing on the main points."
            )
        elif conversation_type == 'Detailed Explanation':
            assistant_style = (
                "As an AI assistant, provide a detailed and comprehensive explanation, covering all relevant aspects."
            )
        else:
            assistant_style = "As an AI assistant, provide a clear and helpful response."

        #remove previous assistant style messages
        conversation_history = [msg for msg in conversation_history if not msg.get('assistant_style')]

        #insert the assistant style message immediately before the last user message
        assistant_style_message = {"role": "system", "content": assistant_style, 'assistant_style': True}
        conversation_history.insert(-1, assistant_style_message)

        #check token count and compress history if necessary
        total_tokens = calculate_total_tokens(conversation_history, model=model_choice)
        max_tokens = 16000 if model_choice == 'gpt-4o' else 4000
        if total_tokens > max_tokens:
            conversation_history = compress_history(conversation_history, model=model_choice)

        response = client.chat.completions.create(
            model=model_choice,
            messages=conversation_history,
            max_tokens=500,
            temperature=0.7,
        )
        answer = response.choices[0].message.content.strip()

        #append the assistant's response to the conversation history
        conversation_history.append({"role": "assistant", "content": answer})

        #update session with conversation history
        session['conversation_history'] = conversation_history

        return jsonify({'response': answer})
    except Exception as e:
        logging.error(f'Unexpected error during chat: {e}')
        return jsonify({'error': f'Unexpected error during chat: {str(e)}'}), 500

if __name__ == '__main__':
    if not os.path.exists('uploads'):
        os.makedirs('uploads')
    app.run(debug=False)
