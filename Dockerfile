# First stage to build/install dependencies

FROM python:3.7-alpine3.7 AS build

RUN mkdir /code
WORKDIR /code

ADD . /code/

RUN apk add --no-cache gcc musl-dev linux-headers
RUN python3 setup.py install


# Second stage to contain built application

FROM python:3.7-alpine3.7

RUN mkdir /code
WORKDIR /code

ADD . /code/

COPY --from=build /usr/local/lib/python3.7/site-packages /usr/local/lib/python3.7/site-packages
