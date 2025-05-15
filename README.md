# LINE Bot with Google ADK (Agent SDK) and Google Gemini

## Project Background

This project is a LINE bot that uses Google ADK (Agent SDK) and Google Gemini models to generate responses to text inputs. The bot can answer questions in Traditional Chinese and provide helpful information. It supports both Google Gemini API and Google VertexAI for model hosting.

## Screenshot

![image](https://github.com/user-attachments/assets/2bcbd827-0047-4a3a-8645-f8075d996c10)

## Features

- Text message processing using AI models (Google ADK or Google Gemini)
- Support for function calling with custom tools
- Integration with LINE Messaging API
- Built with FastAPI for high-performance async processing
- Containerized with Docker for easy deployment

## Technologies Used

- Python 3.9+
- FastAPI
- LINE Messaging API
- Google ADK (Agent SDK)
- Google Gemini API
- Google VertexAI (optional alternative to Gemini API)
- Docker
- Google Cloud Run (for deployment)

## Setup

1. Clone the repository to your local machine.
2. Set the following environment variables:
   - `ChannelSecret`: Your LINE channel secret
   - `ChannelAccessToken`: Your LINE channel access token
   - For Google Gemini API:
     - `GOOGLE_API_KEY`: Your Google Gemini API key
   - For VertexAI (alternative to Gemini API):
     - `GOOGLE_GENAI_USE_VERTEXAI`: Set to "True" to use VertexAI
     - `GOOGLE_CLOUD_PROJECT`: Your Google Cloud Project ID
     - `GOOGLE_CLOUD_LOCATION`: Your Google Cloud region (e.g., "us-central1")

3. Install the required dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Start the FastAPI server:

   ```bash
   uvicorn main:app --reload
   ```

5. Set up your LINE bot webhook URL to point to your server's endpoint.

## Usage

### Text Processing

Send any text message to the LINE bot, and it will use the configured AI model to generate a response. The bot is optimized for Traditional Chinese responses.

### Available Tools

The bot can be configured with various function tools such as:

- Weather information retrieval
- Translation services
- Data lookup capabilities
- Custom tools based on your specific needs

## Deployment Options

### Local Development

Use ngrok or similar tools to expose your local server to the internet for webhook access:

```bash
ngrok http 8000
```

### Docker Deployment

You can use the included Dockerfile to build and deploy the application:

```bash
docker build -t linebot-adk .
# For Gemini API:
docker run -p 8000:8000 \
  -e ChannelSecret=YOUR_SECRET \
  -e ChannelAccessToken=YOUR_TOKEN \
  -e GOOGLE_API_KEY=YOUR_GOOGLE_API_KEY \
  linebot-adk

# For VertexAI:
docker run -p 8000:8000 \
  -e ChannelSecret=YOUR_SECRET \
  -e ChannelAccessToken=YOUR_TOKEN \
  -e GOOGLE_GENAI_USE_VERTEXAI=True \
  -e GOOGLE_CLOUD_PROJECT=YOUR_GCP_PROJECT \
  -e GOOGLE_CLOUD_LOCATION=YOUR_GCP_REGION \
  linebot-adk
```

### Google Cloud Deployment

#### Prerequisites

1. Install the [Google Cloud SDK](https://cloud.google.com/sdk/docs/install)
2. Create a Google Cloud project and enable the following APIs:
   - Cloud Run API
   - Container Registry API or Artifact Registry API
   - Cloud Build API

#### Steps for Deployment

1. Authenticate with Google Cloud:

   ```bash
   gcloud auth login
   ```

2. Set your Google Cloud project:

   ```bash
   gcloud config set project YOUR_PROJECT_ID
   ```

3. Build and push the Docker image to Google Container Registry:

   ```bash
   gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/linebot-adk
   ```

4. Deploy to Cloud Run:

   For Gemini API:
   ```bash
   gcloud run deploy linebot-adk \
     --image gcr.io/YOUR_PROJECT_ID/linebot-adk \
     --platform managed \
     --region asia-east1 \
     --allow-unauthenticated \
     --set-env-vars ChannelSecret=YOUR_SECRET,ChannelAccessToken=YOUR_TOKEN,GOOGLE_API_KEY=YOUR_GOOGLE_API_KEY
   ```

   For VertexAI (recommended for production):
   ```bash
   gcloud run deploy linebot-adk \
     --image gcr.io/YOUR_PROJECT_ID/linebot-adk \
     --platform managed \
     --region asia-east1 \
     --allow-unauthenticated \
     --set-env-vars ChannelSecret=YOUR_SECRET,ChannelAccessToken=YOUR_TOKEN,GOOGLE_GENAI_USE_VERTEXAI=True,GOOGLE_CLOUD_PROJECT=YOUR_GCP_PROJECT,GOOGLE_CLOUD_LOCATION=YOUR_GCP_REGION
   ```

   Note: For production, it's recommended to use Secret Manager for storing sensitive environment variables.

5. Get the service URL:

   ```bash
   gcloud run services describe linebot-adk --platform managed --region asia-east1 --format 'value(status.url)'
   ```

6. Set the service URL as your LINE Bot webhook URL in the LINE Developer Console.

#### Setting Up Secrets in Google Cloud (Recommended)

For better security, store your API keys as secrets:

1. Create secrets for your sensitive values:

   ```bash
   echo -n "YOUR_SECRET" | gcloud secrets create line-channel-secret --data-file=-
   echo -n "YOUR_TOKEN" | gcloud secrets create line-channel-token --data-file=-
   
   # For Gemini API
   echo -n "YOUR_GOOGLE_API_KEY" | gcloud secrets create google-api-key --data-file=-
   
   # For VertexAI (store configuration as secrets if needed)
   echo -n "True" | gcloud secrets create google-genai-use-vertexai --data-file=-
   echo -n "YOUR_GCP_PROJECT" | gcloud secrets create google-cloud-project --data-file=-
   echo -n "YOUR_GCP_REGION" | gcloud secrets create google-cloud-location --data-file=-
   ```

2. Give the Cloud Run service access to these secrets:

   ```bash
   gcloud secrets add-iam-policy-binding line-channel-secret --member=serviceAccount:YOUR_PROJECT_NUMBER-compute@developer.gserviceaccount.com --role=roles/secretmanager.secretAccessor
   gcloud secrets add-iam-policy-binding line-channel-token --member=serviceAccount:YOUR_PROJECT_NUMBER-compute@developer.gserviceaccount.com --role=roles/secretmanager.secretAccessor
   
   # For Gemini API
   gcloud secrets add-iam-policy-binding google-api-key --member=serviceAccount:YOUR_PROJECT_NUMBER-compute@developer.gserviceaccount.com --role=roles/secretmanager.secretAccessor
   
   # For VertexAI (if storing configurations as secrets)
   gcloud secrets add-iam-policy-binding google-genai-use-vertexai --member=serviceAccount:YOUR_PROJECT_NUMBER-compute@developer.gserviceaccount.com --role=roles/secretmanager.secretAccessor
   gcloud secrets add-iam-policy-binding google-cloud-project --member=serviceAccount:YOUR_PROJECT_NUMBER-compute@developer.gserviceaccount.com --role=roles/secretmanager.secretAccessor
   gcloud secrets add-iam-policy-binding google-cloud-location --member=serviceAccount:YOUR_PROJECT_NUMBER-compute@developer.gserviceaccount.com --role=roles/secretmanager.secretAccessor
   ```

3. Deploy with secrets:

   For Gemini API:
   ```bash
   gcloud run deploy linebot-adk \
     --image gcr.io/YOUR_PROJECT_ID/linebot-adk \
     --platform managed \
     --region asia-east1 \
     --allow-unauthenticated \
     --update-secrets=ChannelSecret=line-channel-secret:latest,ChannelAccessToken=line-channel-token:latest,GOOGLE_API_KEY=google-api-key:latest
   ```
   
   For VertexAI:
   ```bash
   gcloud run deploy linebot-adk \
     --image gcr.io/YOUR_PROJECT_ID/linebot-adk \
     --platform managed \
     --region asia-east1 \
     --allow-unauthenticated \
     --update-secrets=ChannelSecret=line-channel-secret:latest,ChannelAccessToken=line-channel-token:latest,GOOGLE_GENAI_USE_VERTEXAI=google-genai-use-vertexai:latest,GOOGLE_CLOUD_PROJECT=google-cloud-project:latest,GOOGLE_CLOUD_LOCATION=google-cloud-location:latest
   ```

## Maintenance and Monitoring

After deployment, you can monitor your service through the Google Cloud Console:

1. View logs: 
   ```bash
   gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=linebot-adk"
   ```

2. Check service metrics: Access the Cloud Run dashboard in Google Cloud Console

3. Set up alerts for error rates or high latency in Cloud Monitoring
