FROM node:20-alpine

RUN apk add --no-cache curl

WORKDIR /app

# Copy package files first for layer caching
COPY package*.json ./

# Install into the image layer; node_modules volume overlays this at runtime
RUN npm install

# Code is mounted as a volume at runtime
COPY . .

EXPOSE 5000

# Re-run npm install on start to pick up any package.json changes, then start nodemon
CMD ["sh", "-c", "npm install && npx nodemon src/server.js"]
