# Build:  docker build -t sudoku .
# Run:    docker run --rm -p 8080:8080 sudoku
# Open:   http://localhost:8080

# download the Supabase browser library with npm.
FROM node:22-alpine AS vendor
WORKDIR /app
COPY Web/package.json Web/package-lock.json ./
RUN npm ci --ignore-scripts

#run the Python server
FROM python:3.12-slim
WORKDIR /app
COPY sudokuMain sudokuMain
COPY Web Web
COPY --from=vendor /app/node_modules Web/node_modules
USER nobody
CMD ["python", "Web/server.py"]
