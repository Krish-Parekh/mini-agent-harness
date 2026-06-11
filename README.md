# MiniAgent Server

## Description
MiniAgent Server is a backend server built with FastAPI that manages conversations and integrates with GitHub.

## Key Features
- FastAPI for building APIs
- CORS support for frontend integration
- Conversation management service
- GitHub integration

## Installation

## Usage Examples

Here are some examples of how to use the API:

### Example 1: Get All Conversations

```bash
curl -X GET http://localhost:8000/api/conversations
```

### Example 2: Create a New Conversation

```bash
curl -X POST http://localhost:8000/api/conversations -H "Content-Type: application/json" -d '{"title": "New Conversation"}'
```

### Example 3: Get a Conversation by ID

```bash
curl -X GET http://localhost:8000/api/conversations/{id}
```

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/Krish-Parekh/mini-agent-harness.git
   cd mini-agent-harness
   ```

2. Set up the environment:
   - Create a `.env` file based on `.env.example` and configure your settings.

3. Start the services using Docker:
   ```bash
   docker-compose up
   ```

## Usage
- The API is accessible at `http://localhost:8000`.
- Endpoints are defined in the `backend/api` directory.

## API Endpoints

### Get All Conversations
- **Endpoint**: `/api/conversations`
- **Method**: `GET`
- **Description**: Retrieves all conversations.

### Create a New Conversation
- **Endpoint**: `/api/conversations`
- **Method**: `POST`
- **Description**: Creates a new conversation.
- **Request Body**: `{ "title": "string" }`

### Get a Conversation by ID
- **Endpoint**: `/api/conversations/{id}`
- **Method**: `GET`
- **Description**: Retrieves a specific conversation by its ID.

## Technologies Used
- FastAPI
- PostgreSQL
- Docker

## Contributing
Contributions are welcome! Please open an issue or submit a pull request.

## FAQs

**Q: How do I set up the environment?**  
A: Create a `.env` file based on `.env.example` and configure your settings.

**Q: What database does this project use?**  
A: This project uses PostgreSQL as the database.

**Q: How can I contribute to the project?**  
A: Contributions are welcome! Please open an issue or submit a pull request.

## License
This project is licensed under the MIT License.