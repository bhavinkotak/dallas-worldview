FROM node:20-alpine
WORKDIR /app
COPY package.json ./package.json
RUN npm install
COPY app ./app
COPY components ./components
COPY public ./public
ENV NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
EXPOSE 3000
RUN npm run build
CMD ["npm", "run", "start"]
