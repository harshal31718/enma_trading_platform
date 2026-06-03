FROM node:20-alpine

WORKDIR /app

# Copy package files first for layer caching
COPY package*.json ./

# Install into the image layer; node_modules volume overlays this at runtime
RUN npm install

# Code is mounted as a volume at runtime
COPY . .

EXPOSE 5173

# Re-run npm install on start to pick up any package.json changes
# --host 0.0.0.0 required to expose Vite outside the container
CMD ["sh", "-c", "npm install && npx vite --host 0.0.0.0"]
