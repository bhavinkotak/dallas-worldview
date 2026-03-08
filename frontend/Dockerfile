FROM node:20-alpine
WORKDIR /app
COPY package.json ./package.json
RUN npm install
COPY app ./app
COPY components ./components
COPY public ./public

# NEXT_PUBLIC_ vars must be present at build time for Next.js to inline them
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
ARG NEXT_PUBLIC_CESIUM_ION_TOKEN=""
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL
ENV NEXT_PUBLIC_CESIUM_ION_TOKEN=$NEXT_PUBLIC_CESIUM_ION_TOKEN

EXPOSE 3000
RUN npm run build
CMD ["npm", "run", "start"]
