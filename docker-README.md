# Docker Deployment Guide

## Quick Start

### Using Docker Compose (Recommended)

1. **Build and start the container:**
   ```bash
   docker-compose up -d
   ```

2. **View logs:**
   ```bash
   docker-compose logs -f
   ```

3. **Stop the container:**
   ```bash
   docker-compose down
   ```

### Using Docker directly

1. **Build the image:**
   ```bash
   docker build -t multilingual-blog .
   ```

2. **Run the container:**
   ```bash
   docker run -d \
     -p 5000:5000 \
     -v $(pwd)/blog.db:/app/blog.db \
     -v $(pwd)/static/uploads:/app/static/uploads \
     -v $(pwd)/static/authors:/app/static/authors \
     -e SECRET_KEY=your-secret-key \
     --name multilingual-blog \
     multilingual-blog
   ```

3. **View logs:**
   ```bash
   docker logs -f multilingual-blog
   ```

4. **Stop and remove:**
   ```bash
   docker stop multilingual-blog
   docker rm multilingual-blog
   ```

## Environment Variables

Create a `.env` file based on `.env.example`:

```bash
cp .env.docker .env
```

Then edit `.env` with your configuration:

- `SECRET_KEY`: Flask secret key (generate a secure random string)
- `APP_ID`: Application identifier
- `APP_NAME`: Blog name
- `DATABASE_PATH`: Path to SQLite database file
- `FLASK_DEBUG`: Set to `False` in production
- `HOST`: Host to bind to (0.0.0.0 for Docker)
- `PORT`: Port to expose (default 5000)

## Data Persistence

The following directories are mounted as volumes to persist data:

- `./blog.db`: SQLite database
- `./static/uploads`: Uploaded media files
- `./static/authors`: Author profile images

## Production Deployment

### Using a Reverse Proxy (Nginx)

1. **Start the blog container:**
   ```bash
   docker-compose up -d
   ```

2. **Configure Nginx** (see `etc/nginx.conf` for example)

3. **Use environment variables for production:**
   ```bash
   # In your .env file
   SECRET_KEY=<generate-strong-secret>
   FLASK_DEBUG=False
   ```

### Security Recommendations

- Always change the default `SECRET_KEY`
- Use HTTPS with a reverse proxy (Nginx, Caddy, Traefik)
- Keep the Docker image updated
- Regularly backup `blog.db` and uploads

## Health Check

The container includes a health check that verifies the blog is responding:

```bash
docker inspect --format='{{json .State.Health}}' multilingual-blog
```

## Updating

1. **Pull latest code:**
   ```bash
   git pull
   ```

2. **Rebuild and restart:**
   ```bash
   docker-compose down
   docker-compose build --no-cache
   docker-compose up -d
   ```

## Troubleshooting

**Container won't start:**
```bash
docker-compose logs blog
```

**Permission issues:**
```bash
chmod -R 755 static/uploads static/authors
```

**Reset database:**
```bash
docker-compose down
rm blog.db
docker-compose up -d
```

## Advanced Usage

### Custom Port

Edit `docker-compose.yml`:
```yaml
ports:
  - "8080:5000"  # Map host port 8080 to container port 5000
```

### Multiple Instances

Run multiple blogs by changing the container name and port:
```bash
docker-compose -p blog2 up -d
```
