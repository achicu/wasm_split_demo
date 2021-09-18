// Copyright 2021 Adobe
// All Rights Reserved.
//
// NOTICE: Adobe permits you to use, modify, and distribute this file in accordance with the terms
// of the Adobe license agreement accompanying it.

const https = require('https');
const fs = require('fs');
const express = require('express');
const app = express();
const port = 8080;

app.use((req, res, next) => {
    res.setHeader('Cross-Origin-Resource-Policy', 'same-origin');
    res.setHeader('Cross-Origin-Embedder-Policy', 'require-corp');
    res.setHeader('Cross-Origin-Opener-Policy', 'same-origin');
    
    next();
});

app.use(express.static('build', { index: 'index.html' }));

const server = https.createServer({
    key: fs.readFileSync('server.key'),
    cert: fs.readFileSync('server.cert')
}, app);

server.listen(port, () => {
    console.log(`Example app listening on port ${port}! Go to https://localhost:${port}/`);
});
