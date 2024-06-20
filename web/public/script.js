function Question(props) {
    return {
        $template: '#question_template',
        question: props,
    }
}

function QuestionSet(props) {
    return {
        $template: '#questionset_template',
        questionset: props,
    }
}


function redirectView() {
    return {
        $template: '#questionset_template',
    }
}

PetiteVue.createApp({
    rasters: [],
    raster: null,
    results: [],
    result: null,
    file: null,
    data: [],
    showPopup: false,
    uploading: false,
    disableUploading: false,
    progress: 0,
    selected: null,
    defaultValue: "Choose template",
    questionset: null, //[],        
    questionset_id: null,
    questionset_name: null,
    questionset_name_list: null,
    questionset_name_valid: true, //false,  
    original_questionset: null,
    showQuestionsetPage: false,
    questionset_dirty: false,
    editing_questionsets: true,
    save_template_msg: "Save Template",
    toggle_questionset_msg: "Hide questionset",
    band_selected: 1,
    effectset: null,
    samples: null,
    msg: null,
    score_invalid: false,
    metrics: null,
    folders: [],
    folder: null,
    deckInstance: null,
    showUploadMessage: false,
    fileName: null,
    search: '',
    showActionConfirmation: false,
    selectedAction: 'upload',
    actionFolder: null,
    showLogs: false,
    ws: null,
    logs: [],
    refresh_folders() {
        fetch(`/folders`, { headers: { "Accept": "application/json" } })
            .then(response => response.ok ? response.json() : Promise.reject(response))
            .then(data => {
                this.folders = data
            });
    },

    select_folder(folder) {
        this.folder = folder;
        console.log(folder);

        if (!folder) {
            window.location.reload(); // hacky but easy. somehow back button gives error.
        } else {
            this.editing_questionsets = false
            // fetch rasters
            fetch(`/folder/raster/${folder.id}`, { headers: { "Accept": "application/json" } })
                .then(response => response.ok ? response.json() : Promise.reject(response))
                .then(data => {
                    this.rasters = data;
                    this.raster = this.rasters[0];
                });
        }
    },
    select_action(action, folder) {
        if (action === "View") {
            this.select_folder(folder)
        } else {
            this.selectedAction = action;
            this.showPopup = true;
            this.actionFolder = folder
        }

        //this.showActionConfirmation = true;
    },
    select_raster(raster) {

        this.raster = raster;
        this.results = raster && raster.status === 'Done' ? [{}] : [];
        this.result = this.results[0] ? this.results.length > 0 : null;
        if (!raster) {
            window.location.reload(); // hacky but easy. somehow back button gives error.
        }
        else {
            this.editing_questionsets = false
        }
    },
    delete_raster(folder) {
        fetch(`/delete_raster/${folder.id}`, { method: "DELETE" })
            .then(response => response.ok ? response : Promise.reject(response))
            .then(response => {
                this.refresh_folders()
            }
            )
    },
    add_new_effect(answer) {
        answer.effects.push({ 'name': 'Replace me', 'value': 0.5 })
        this.questionset_dirty = true
    },
    add_new_question(questionset) {
        questionset.push({ text: "Replace me", answers: [] })
        this.questionset_dirty = true
    },
    add_new_questionset() {
        this.set_value_null()
        this.questionset = [];

    },
    delete_question(parent, question) {
        parent.splice(parent.indexOf(question), 1)
        this.questionset_dirty = true
    },
    delete_answer(parent, answer) {
        parent.splice(parent.indexOf(answer), 1)
        this.questionset_dirty = true
    },
    delete_effect(parent, effect) {
        parent.splice(parent.indexOf(effect), 1)
        this.questionset_dirty = true
    },
    add_new_answer(question) {
        question.answers.push({ text: "Replace me", subquestions: [], effects: [] })
        this.questionset_dirty = true
    },
    load_questions() {
        fetch(`/raster/questions`, { headers: { "Accept": "application/json" } })
            .then(response => response.ok ? response.json() : Promise.reject(response))
            .then(data => {
                const tmp_map = {} //for reset()
                this.questionset_name_list = data.map(function (item) {
                    tmp_map[item.id] = item.data
                    return item.name;
                });
                this.original_questionset = JSON.parse(JSON.stringify(tmp_map)) //deep copy
                this.data = data;
                this.set_value_null()
            }).catch(error => {
                var message = document.getElementById('message-block');
                message.textContent = "Error fetching questionset! Please try again later.";
                message.style.color = "Red";
                console.log(error);
            });
    },
    set_selected() {
        this.questionset = this.selected.data.questionset
        this.questionset_name = this.selected.name
        this.questionset_id = this.selected.id
        this.questionset_name_valid = true
        this.questionset_dirty = false

        this.samples = null
        this.effectset = null
        this.msg = null
        this.save_template_msg = "Update Template" // if exist template
    },
    set_value_null() {
        this.selected = null
        this.questionset = null
        this.questionset_name = null
        this.questionset_id = null
        // this.questionset_name_valid = false
        this.questionset_dirty = false
        this.samples = null
        this.effectset = null
        this.msg = null
        this.save_template_msg = "Save Template"
    },
    update_questionset(event) {
        this.set_selected()
    },
    input_dirty() {
        this.questionset_dirty = true
    },

    check_float(value) {
        this.questionset_dirty = true
        if (value >= 0.0 && value <= 1.0) {
            this.score_invalid = false
        } else {
            this.score_invalid = true
            return "Enter valid value between [0.0-1.0]."
        }
    },
    check_name() {
        if (this.questionset_name != null & this.questionset_name_list.includes(this.questionset_name)) {
            this.questionset_name_valid = false
        } else {
            this.questionset_name_valid = true
            this.questionset_dirty = true
        }
    },
    reset() { // reset current selected template, if dirty, to original state (when first loaded)
        let id = this.selected.id
        let original_item = this.original_questionset[id]
        this.questionset_name = original_item.questionset_name
        let tmp_qs = original_item.questionset
        this.questionset = JSON.parse(JSON.stringify(tmp_qs))
        this.selected.data.questionset = JSON.parse(JSON.stringify(tmp_qs))
    },
    delete_template() {
        let id = this.questionset_id
        fetch(`/raster/delete_questionset/${id}`, { headers: { "Accept": "application/json" } })
            .then(response => response.ok ? response : Promise.reject(response))
            .then(response => {
                this.load_questions(); // to update select box immediately
            }
            )
    },
    validate() {
        json_data = { "questionset": this.questionset, "name": this.questionset_name }
        fetch('/raster/questions/validate', {
            method: "POST",
            body: JSON.stringify(json_data),
            headers: { "Content-Type": "application/json" }
        })
            .then(response => response.ok ? response.json() : Promise.reject(response))
            .then(data => {
                this.effectset = null
                this.msg = data.msg
                this.samples = data.samples
                this.effectset = data.effectset
                var result = document.getElementById('validation-result');
                result.scrollIntoView({ behavior: 'smooth' });
            });
    },
    save_questionset(save_as = false) {
        console.log('ques', this.questionset)
        if (!this.questionset | !this.questionset.length) {
            alert("There is no questionset to save!")
            return
        }
        if (!this.questionset_name) {
            alert("Please enter template name!")
            return
        }
        if (save_as) this.questionset_id = null
        json_data = {
            "questionset_name": this.questionset_name,
            "questionset": this.questionset,
            "questionset_id": this.questionset_id
        }

        fetch('/raster/questions', {
            method: "POST",
            body: JSON.stringify(json_data),
            headers: { "Content-Type": "application/json" }
        })
            .then(response => response.ok ? response : Promise.reject(response))
            .then(data => {
                window.location.reload();
            }
            )
    },
    toggle_questionset() {
        this.editing_questionsets = !this.editing_questionsets
        this.toggle_questionset_msg = this.editing_questionsets ? "Hide questionset" : "Show questionset"
    },

    stage_raster(file) {
        this.file = file;
    },
    get filter_folders() {
        if (!this.search.trim()) {
            return this.folders;
        }
        return this.folders.filter(folder => {
            const lowerCaseSearch = this.search.toLowerCase();
            return folder.name.toLowerCase().includes(lowerCaseSearch); //|| folder.questionset.includes(lowerCaseSearch)
        });
    },
    upload_raster() {
        this.progress = 0;
        if (this.file == null) {
            alert("Choose file");
            return
        }
        if (this.questionset_id == null) {
            alert("Choose template");
            return
        }
        let form_data = new FormData();
        form_data.append("file", this.file);
        form_data.append("questionset_id", this.questionset_id); // get questionset in web.py

        const xhr = new XMLHttpRequest();
        xhr.open('POST', '/rasters'); // Replace with your actual upload URL

        // Event listener for when the upload progresses
        xhr.upload.onprogress = (event) => {
            if (event.lengthComputable) {
                this.progress = (event.loaded / event.total) * 100;
            }
        };

        // Event listener for when the upload completes
        xhr.onload = () => {
            
            var message = document.getElementById("upload-message");
            if (xhr.status === 200) {
                message.textContent = "The file has been submitted for processing.";
                message.style.color = "green";
            } else {
                message.textContent = "Submit Failed! Please try again.";
                message.style.color = "Red";
            }
            this.showUploadMessage = true;
            this.refresh_folders();
            this.disableUploading = false;

        };

        // Event listener for when the upload starts
        xhr.upload.onloadstart = () => {
            this.uploading = true;
            this.disableUploading = true;
        };

        // Event listener for when the upload fails
        xhr.onerror = () => {
            this.uploading = false;
            this.disableUploading = false;
        };

        xhr.send(form_data);

    },
    reset_form() {
        this.file = null;
        this.fileName = null;
        this.selected = null;
        const form = document.querySelector('.popup form');
        if (form) {
            form.reset();
        }
    },
    close_popup() {
        this.uploading = false;
        this.showPopup = false;
        this.reset_form();
        this.refresh_folders();
    },
    connect() {
        const websocketUrl = `${(window.location.protocol === "https:" ? "wss://" : "ws://")}${window.location.host}/ws`;
        this.ws = new WebSocket(websocketUrl);

        this.ws.onopen = () => {
            //   this.ws.send('start');  // Send the start message to begin log streaming
        };
        this.ws.onmessage = (event) => {
            const newLogs = event.data.split(/\r?\n/);
            newLogs.forEach(log => {
                if (log.trim() !== '') {
                    this.logs.push(this.highlightKeywords(log));

                }
            });
        };
    },
    highlightKeywords(log) {
        const keywords = { 'INFO': 'keyword-info', 'DEBUG': 'keyword-debug', 'WARNING': 'keyword-warning', 'ERROR': 'keyword-error' };
        const regex = new RegExp(`\\b(${Object.keys(keywords).join('|')})\\b`, 'g');
        return log.replace(regex, match => `<span class="${keywords[match]}">${match}</span>`);
    },
    initialise_map(raster, band_selected) {

        if (this.deckInstance) {
            this.deckInstance.finalize();
            this.deckInstance = null;
            const mapContainer = document.getElementById('map');
            mapContainer.innerHTML = '';
        }
        let min_zoom = 2;
        let max_zoom = 20;
        let latlon = raster.latlon;
        let protocol = window.location.protocol;
        let mapSize = document.getElementById("map").getBoundingClientRect();
        if (latlon) {

            let baseLayer = new deck.TileLayer({
                id: "base",
                data: `${protocol}//a.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}.png`,
                tileSize: 256,
                minZoom: min_zoom,
                maxZoom: max_zoom,
                coordinateSystem: deck.COORDINATE_SYSTEM.LNGLAT,
                renderSubLayers: props => {
                    const {
                        bbox: { west, south, east, north }
                    } = props.tile;

                    return new deck.BitmapLayer(props, {
                        data: null,
                        image: props.data,
                        bounds: [west, south, east, north]
                    });
                }
            });

            let sourceLayer = new deck.TileLayer({
                id: "source",
                data: `/rasters/${raster.id}/tiles/{z}/{y}/{x}.png`,
                tileSize: 256,
                minZoom: min_zoom,
                maxZoom: max_zoom,
                coordinateSystem: deck.COORDINATE_SYSTEM.LNGLAT,

                renderSubLayers: props => {
                    const {
                        bbox: { west, south, east, north }
                    } = props.tile;

                    return new deck.BitmapLayer(props, {
                        data: null,
                        image: props.data,
                        bounds: [west, south, east, north]
                    });

                }
            });

            // fix end point & add toggle & look into deck lib to manipulate band 
            let resultLayer = new deck.TileLayer({
                id: "result",
                data: `/rasters/${raster.id}/results/${band_selected}/tiles/{z}/{y}/{x}.png`,
                tileSize: 256,
                minZoom: min_zoom,
                maxZoom: max_zoom,
                coordinateSystem: deck.COORDINATE_SYSTEM.LNGLAT,
                renderSubLayers: props => {
                    const {
                        bbox: { west, south, east, north }
                    } = props.tile;

                    return new deck.BitmapLayer(props, {
                        data: null,
                        image: props.data,
                        bounds: [west, south, east, north]
                    });
                }
            });

            let labelsLayer = new deck.TileLayer({
                id: "labels",
                data: `${protocol}//a.basemaps.cartocdn.com/light_only_labels/{z}/{x}/{y}.png`,
                tileSize: 256,
                minZoom: min_zoom,
                maxZoom: max_zoom,
                coordinateSystem: deck.COORDINATE_SYSTEM.LNGLAT,

                renderSubLayers: props => {
                    const {
                        bbox: { west, south, east, north }
                    } = props.tile;

                    return new deck.BitmapLayer(props, {
                        data: null,
                        image: props.data,
                        bounds: [west, south, east, north]
                    });
                }
            });

            let viewport = new deck.WebMercatorViewport({
                width: mapSize.width,
                height: mapSize.height
            }).fitBounds([[latlon[0], latlon[1]], [latlon[2], latlon[3]]], { padding: 10 })

            this.deckInstance = new deck.DeckGL({
                container: 'map',
                mapStyle: `${protocol}//basemaps.cartocdn.com/gl/positron-gl-style/style.json`,
                initialViewState: {
                    longitude: viewport.longitude,
                    latitude: viewport.latitude,
                    zoom: viewport.zoom - 0.2
                },
                views: [new deck.MapView({ repeat: true })],
                controller: true,
                layers: [baseLayer, sourceLayer, resultLayer, labelsLayer],
            });
        } else {
            let aspectRatio = raster.width / raster.height;
            let zoom;
            if (mapSize.height > raster.height) {
                zoom = (mapSize.height / raster.height) * 2;
            } else {
                zoom = (raster.height / mapSize.height) * 2;
            }
            let sourceLayer = new deck.BitmapLayer({
                id: "source",
                image: `/rasters/source/${raster.id}.png`,
                bounds: [-aspectRatio / 2, -0.5, aspectRatio / 2, 0.5],
            });

            // fix end point & add toggle & look into deck lib to manipulate band 
            let resultLayer = new deck.BitmapLayer({
                id: "result",
                image: `/rasters/dest/${raster.id}/${band_selected}/result.png`,
                bounds: [-aspectRatio / 2, -0.5, aspectRatio / 2, 0.5],
            });


            this.deckInstance = new deck.DeckGL({
                container: 'map',
                mapStyle: null,
                initialViewState: {
                    longitude: 0,
                    latitude: 0,
                    zoom: zoom,
                    pitch: 0,
                    bearing: 0
                },
                controller: true,
                layers: [sourceLayer, resultLayer],
            });
        }


    }
}).mount()
