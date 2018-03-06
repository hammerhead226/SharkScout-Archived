var storage = function(container, key, val) {
    // Grab store, enforce it to be an object
    var c = store.get(container);
    if(!_.isObject(c)) {
        c = {};
    }
    if(typeof(val) == 'undefined') {
        if(typeof(key) == 'undefined') {
            // No params, return container
            return c;
        } else {
            // 'key' param, return property value
            return c[key];
        }
    } else {
        // 'key' and 'val' params, set property value
        c[key] = val;
        return store.set(container, c);
    }
};
var forms = function(key, val) {
    return storage('forms', key, val);
};
var queue = function(key, val) {
    if(typeof(val) != 'undefined') {
        $('#icon-queue').removeClass('animated').stop().fadeIn();
    }
    val = storage('queue', key, val);
    // 'key' param, enforce property value is an array
    if(typeof(val) == 'undefined' && typeof(key) != 'undefined' && !_.isArray(val)) {
        val = [];
    }
    return val;
};


var ws_online = true;
function openSocket() {
    var webSocket = 'ws://' + window.location.hostname + ':' + window.location.port + '/ws'
    var pingInterval;
    var pingCount = 0;
    var timeTeamInterval;
    var timeTeamLast = undefined;
    var submitInterval;

    if(window.WebSocket) {
        var ws = new WebSocket(webSocket);
    } else if(window.MozWebSocket) {
        var ws = MozWebSocket(webSocket);
    }

    ws.onopen = function() {
        // Keep testing the WebSocket connection
        var ping = function() {
            // Too many pings were not ponged, assume disconnected
            if(pingCount >= 5) {
                // ws.close() doesn't work, it asks host to close
                ws.onclose();
                return;
            }
            ws.send(JSON.stringify({'ping':'ping'}));
            pingCount++;
        }
        pingInterval = setInterval(ping, 500);
        ping();

        // Send time team requests every minute
        var timeTeam = function() {
            var now = moment();
            if(typeof(timeTeamLast) == 'undefined' || timeTeamLast.format('YYYY/MM/DD HH:mm') != now.format('YYYY/MM/DD HH:mm')) {
                ws.send(JSON.stringify({'time_team':'frc' + _.trimStart(now.format('HHmm'),'0')}));
                timeTeamLast = now;
            }
        }
        timeTeamInterval = setInterval(timeTeam, 100);
        timeTeam();

        var submit = function() {
            for(var key in queue()) {
                if(queue(key).length) {
                    ws.send(JSON.stringify(queue()));
                    $('#icon-queue').addClass('animated')
                    return;
                }
            }
        };
        submitInterval = setInterval(submit, 5000);
        submit();

        $('#icon-no-websocket').stop().fadeOut();
        ws_online = true;
    };

    ws.onmessage = function(e) {
        var data = JSON.parse(e.data);

        // Record if our ping was ponged
        if(data.pong) {
            pingCount--;
        }

        // Show elements
        if(data.show) {
            $(data.show).show();
        }

        // Handle time team messages
        if(data.time_team) {
            $('#time').html('<span title="' + timeTeamLast.format('MMM D, YYYY h:mm A') + '">' + timeTeamLast.format('HH:mm') + '</span>');
            if(typeof(data.time_team['key']) != 'undefined') {
                $('#time_team').html('<a href="/team/' + data.time_team['key'] + '">' + data.time_team['nickname'] + '</a>');
            } else {
                $('#time_team').html('');
            }
        }

        // Dequeue messages
        if(data.dequeue) {
            for(var key in data.dequeue) {
                var i = 0;
                while(i < queue(key).length) {
                    if(_.isEqual(queue(key)[i], data.dequeue[key])) {
                        var val = queue(key);
                        val.splice(i, 1);
                        queue(key, val);
                    } else {
                        i++;
                    }
                }
            }
        }
        // Detect empty queue, hide queue icon if empty
        for(var key in queue()) {
            if(queue(key).legnth) {
                return;
            }
        }
        $('#icon-queue').removeClass('animated').stop().fadeOut();
    };

    ws.onclose = function(e) {
        clearInterval(pingInterval);
        clearInterval(submitInterval);

        $('#icon-no-websocket').stop().fadeIn();
        ws_online = false;
        setTimeout(openSocket, 1000);
    };
}
$(document).ready(function() {
    openSocket();
});


function _scouting(ref, key) {
    if(typeof(ref) == 'object' && ref.nodeType === 1) {
        var obj = serialize(ref);
        var scouting = queue(key);

        // Non-ASCII check
        for(var name in obj) {
            if(String(obj[name]).match(/[^\x09-\x7E]/)) {
                return;
            }
        }

        // Duplicate check
        for(var i = 0; i < scouting.length; i++) {
            if(_.isEqual(scouting[i], obj)) {
                return;
            }
        }

        scouting.push(obj);
        queue(key, scouting);

        if(ws_online) {
            window.location.href = '/event/' + $(ref).find('[name="event_key"]').val();
        } else {
            $('#queued').show();
            setTimeout(function() {
                $('#queued').stop().fadeOut();
            }, 5000);
            $(ref)[0].reset();
            $('html').scrollTop(0);
        }

        // Clear stored temporary form data
        forms(window.location.pathname, {});
    }
}

function scouting_match(ref) {
    _scouting(ref, 'scouting_match');
}

function scouting_pit(ref) {
    _scouting(ref, 'scouting_pit');
}

function serialize(form, serializeAll) {
    if(typeof serializeAll === 'undefined') {
        serializeAll = false;
    }

    var obj = {};
    var $inputs = $(form).find('input, select, textarea');
    if(!serializeAll) {
        $inputs = $inputs.not('[serialize="false"]');
    }
    $inputs.each(function() {
        var $input = $(this);
        var key = $input.attr('name') || $input.id;

        // Init arrays
        if(key && key.substring(key.length-2) == '[]') {
            if(!_.isArray(obj[key.substring(0,key.length-2)])) {
                obj[key.substring(0,key.length-2)] = [];
            }
        }

        // Skip inputs that shouldn't be recorded
        if($input.is('[type="checkbox"], [type="radio"]') && !$input.is(':checked')) {
            return;
        }

        // Record values
        if(key) {
            var val = $input.val();
            val = val && !isNaN(val) ? +val : val;
            if($input.is('[type="checkbox"]') && key.substring(key.length-2) == '[]') {
                // Handle multi-checkboxes
                obj[key.substring(0,key.length-2)].push(val);
            } else {
                // Handle everything else
                obj[key] = val;
            }
        }
    });
    return obj;
}

function deserialize(form, data) {
    if(!_.isObject(data) && _.isString(data)) {
        data = JSON.parse(data);
    }

    for(var name in data) {
        // Massage values into an array
        var values = _.isArray(data[name]) ? data[name] : [data[name]];
        for(key in values) {
            // Find the correct element
            var $tag = $(form).find('[name="' + name + '"], [name="' + name + '[]"]').not(':disabled');
            if($tag.closest('.btn-group .btn.disabled').length) {
                continue;
            }
            if($tag.length > 1) {
                $tag = $tag.filter('[value="' + values[key] + '"]');
            }
            // Set the value appropriately
            if($tag.length) {
                if($tag.is('[type="checkbox"], [type="radio"]')) {
                    $tag.click();
                } else if($tag.is('.selectized')) {
                    $tag[0].selectize.setValue(values[key], true);
                } else {
                    $tag.val(values[key]);
                }
                $tag.change();
            }
        }
    }
}


// Initialize page
$(document).ready(function() {
    // Block page changes when offline
    $('a[href]:not([href^="#"]), [onclick]:not([onclick=""]), button[type="submit"]')
        .not('[offline], a[target="_blank"], [data-toggle="dropdown"]').click(function(e) {
            if(!ws_online) {
                $('#offline').modal();
                e.preventDefault();
            }
    });

    // btn-group behavior
    $('.btn-group[data-toggle="buttons"] > .btn').click(function(e) {
        var $btn = $(this);
        // btn-group disabling
        if($btn.is('.disabled')) {
            e.preventDefault();
            return false;
        }
        // btn-group styling
        $btn.children('input[type="checkbox"]').each(function() {
            if($(this).is(':checked')) {
                $btn.addClass('btn-primary');
            } else {
                $btn.removeClass('btn-primary');
            }
        });
        if($btn.children('input[type="radio"]').length) {
            $btn.addClass('btn-primary');
            var $btn_group = $().add($btn.closest('.btn-toolbar').children('.btn-group')).add($btn.closest('.btn-group'));
            $btn_group.children('.btn').not(this).removeClass('btn-primary active');
        }
    });

    // btn data-toggle subtract/add behavior
    $('.btn[data-toggle="subtract"], .btn[data-toggle="add"]').not('[data-target]').click(function() {
        // Allow data-target to be optional, find it and set it
        var $btn = $(this);
        if(!$btn.is('[data-target]')) {
            $btn.attr('data-target', $btn.closest('.input-group-btn').siblings('input').attr('name'));
         }
    });
    $('.btn[data-toggle="subtract"]').click(function() {
        var $input = $('[name="' + $(this).attr('data-target') + '"]');
        if($input.is('[min]') && parseInt($input.val())-1 < $input.attr('min')){ return; }
        $input.val(parseInt($input.val())-1);
    });
    $('.btn[data-toggle="add"]').click(function() {
        var $input = $('[name="' + $(this).attr('data-target') + '"]');
        if($input.is('[max]') && parseInt($input.val())+1 > $input.attr('max')){ return; }
        $input.val(parseInt($input.val())+1);
    });

    // Click the first tab on any nav-tabs without an active tab
    $('ul.nav-tabs').each(function() {
        if(!$(this).children('li.active').length) {
            $(this).children('li').children('a').first().click();
        }
    });
    // Click the appropriate nav-tab tab if there's a hash in URL
    if(window.location.hash && $('#'+window.location.hash.substring(1)+'.tab-page:not(.active)').length) {
        $('ul.nav-tabs > li > a[href="' + window.location.hash + '"]').click();
    }
    // Clicks on nav-tab tab will put it in the window location
    $('ul.nav-tabs > li > a[href^="#"]').click(function() {
        var href = $(this).attr('href');
        var $tab_page = $('#'+href.substring(1)+'.tab-page');
        if($tab_page.length && !$tab_page.hasClass('active')) {
            if(window.history.pushState) {
                window.history.pushState(null, null, href);
            } else {
                window.location.hash = href;
            }
        }
    });

    // Initialize selectize on all <select>s (if not IE because native form validation fails?)
    if(!detectIE()) {
        $('select').each(function() {
            var options = {
                'persist': false
            };
            $.each(this.attributes, function() {
                if(this.name.match(/^data-selectize-/)) {
                    options[this.name.replace(/^data-selectize-/,'')] = this.value;
                }
            });
            $(this)
                .selectize(options)
                .find('.selectize-input input').change(function() {
                    this.blur();
                });
        });
    }

    // Initialize Chart.js
    $('canvas.chart').each(function() {
        // Get array of labels
        var labels = _.split($(this).siblings('input[name="labels"]').val(), ',');
        if(labels.length == 1 && labels[0] == '') {
            labels = [];
        }
        // Get array of array of values
        var values = $(this).siblings('input[name="values"]').map(function() {
            // (Array() because jQuery flattens arrays...)
            return Array(_.map(_.split(this.value, ','), function(val) {
                return parseFloat(val);
            }));
        }).get();
        var maxValues = _.max(_.map(values, function(v){return v.length;}));
        // Find max value
        var maxValue = 0;
        for(var i = 0; i < maxValues; i++) {
            for(var j = 0; j < values.length; j++) {
                if(i < values[j].length && values[j][i] > maxValue) {
                    maxValue = values[j][i];
                }
            }
        }
        // Calculate averages
        var averages = Array(maxValues);
        for(var i = 0; i < averages.length; i++) {
            var sum = 0;
            var count = 0;
            for(var j = 0; j < values.length; j++) {
                if(i < values[j].length) {
                    sum += values[j][i];
                    count++;
                }
            }
            averages[i] = sum / count;
        }
        // Calculate regression for averages
        var fitted = regressionFit(
            _.map(averages, function(y, x) {
                return [x+1, y];
            })
        );
        // Plot the chart
        new Chart(this, {
            'type': 'line',
            'data': {
                'labels': Array(maxValues),
                'datasets': _.map(values, function(val, idx) {
                    // Raw data set(s)
                    return {
                        'label': labels.length == values.length ? labels[idx] : '',
                        'data': val,
                        'borderColor': ['#337ab7','#5cb85c','#5bc0de','#f0ad4e','#d9534f'][idx%5],
                        'backgroundColor': ['rgba(51,122,182,0.5)','rgba(92,184,92,0.5)','rgba(91,192,222,0.5)','rgba(240,173,78,0.5)','rgba(217,83,79,0.5)'][idx%5],
                        'borderWidth': 3,
                        'fill': false
                    };
                }).concat([{
                    'data': _.map(Array(maxValues), function(y, x) {
                        return fitted.predict(x+1)[1];
                    }),
                    'borderColor': '#777777',
                    'backgroundColor': 'rgba(119,119,119,0.2)',
                    'borderWidth': 2,
                    'borderDash': [15, 10],
                    'pointRadius': 0,
                    'pointHoverRadius': 0
                }])
            },
            'options': {
                'layout': {
                    'padding': 5
                },
                'legend': {
                    'display': labels.length == values.length,
                    'labels': {
                        'filter': function(item) {
                            return typeof(item.text) !== 'undefined' && item.text;
                        },
                        'boxWidth': 15
                    }
                },
                'scales': {
                    'yAxes': [{
                        'ticks': {
                            'display': false,
                            'min': 0,
                            'max': maxValue
                        },
                        'gridLines': {
                            'display': true
                        }
                    }],
                    'xAxes': [{
                        'ticks': {
                            'display': false,
                            'stepSize': 1
                        },
                        'gridLines': {
                            'display': true
                        }
                    }]
                },
                'maintainAspectRatio': false,
                // Performance tuning
                'animation': {
                    'duration': 0
                },
                'hover': {
                    'animationDuration': 0
                },
                'responsiveAnimationDuration': 0
            }
        });
    });

    // Initialize DataTable on all Bootstrap <table>s
    $('table.table').filter(function(){return !$(this).find('*[colspan],*[rowspan]').length;}).each(function() {
        var $table = $(this);
        var table = $table.DataTable({
            'paging': false,  // disable paging
            'info': false,    // disable footer (not needed with no paging)
            'filter': false,  // disable filtering
            'order': [],      // disable initial sorting
            'autoWidth': false,
            'fixedHeader': true
        });
        // Handle DataTable FixedHeader with nav-tab changes
        var $tab_toggle = $('a[href="#' + $table.closest('.tab-page').attr('id') + '"][data-toggle="tab"]');
        if($tab_toggle.length) {
            $tab_toggle.on('shown.bs.tab', function() {
                table.fixedHeader.enable();
            });
            $tab_toggle.on('hide.bs.tab', function() {
                table.fixedHeader.disable();
            });
            if(!$tab_toggle.is(':visible')) {
                table.fixedHeader.disable();
            }
        }
    });

    // Initialize non-ASCII popovers
    $('form').find('input, select, textarea').popover({
        trigger: 'manual',
        placement: 'auto',
        content: 'Special characters are not allowed.'
    }).change(function() {
        if(String($(this).val()).match(/[^\x09-\x7E]/)) {
            $(this).popover('show');
            nonAscii = true;
        } else {
            $(this).popover('hide');
        }
    });

    // Handle form key building
    $('[name="comp_level"], [name="match_number"], [name="set_number"]').change(function() {
        if($('[name="comp_level"]').val() == '' || $('[name="comp_level"]').val() == 'qm') {
            $('[name="set_number"]').removeAttr('required').closest('.input-group').hide();
        } else {
            $('[name="set_number"]').attr('required','required').closest('.input-group').show();
        }
        $('[name="match_key"]').val(
            $('[name="event_key"]').val() + '_' +
            $('[name="comp_level"]').val() +
            ($('[name="set_number"]').is(':visible') ? $('[name="set_number"]').val() + 'm' : '') +
            $('[name="match_number"]').val()
        );
    });
    $('[name="team_number"]').change(function() {
        $('[name="team_key"]').val('frc' + $(this).val());
    });
    // Handle form deserialization
    var $saved = $('[name="saved"]');
    if($saved.length) {
        deserialize($saved.closest('form'), $saved.val());
    }

    // Store temporary form data on change, and restore it on page load (make navigation non-destructive)
    $('form[persistent="true"]').first().each(function() {
        deserialize(this, forms(window.location.pathname));
    }).find('input, select, textarea').change(function() {
        forms(window.location.pathname, serialize($(this).closest('form'), true));
    });
});


function loader(ref) {
    var $ref = $(ref);
    // Find dropdown button
    var $dropdown_menu = $ref.parents('.dropdown-menu');
    if($dropdown_menu.length) {
        $ref = $dropdown_menu.siblings('.dropdown-toggle');
    }
    // Disable
    if(!$ref.hasClass('disabled')) {
        if($ref.prop('tagName') == 'button') {
            $ref.attr('disabled', 'disabled');
        }
        $ref.addClass('disabled');
        $ref.find('.fa').addClass('fa-spin');
        $('body > .mask').show();
        return true;
    }
    return false;
}

// http://codepen.io/gapcode/pen/vEJNZN
function detectIE() {
    var ua = window.navigator.userAgent;
    var msie = ua.indexOf('MSIE ');
    if (msie > 0) {
        return parseInt(ua.substring(msie + 5, ua.indexOf('.', msie)), 10);
    }
    var trident = ua.indexOf('Trident/');
    if (trident > 0) {
        var rv = ua.indexOf('rv:');
        return parseInt(ua.substring(rv + 3, ua.indexOf('.', rv)), 10);
    }
    var edge = ua.indexOf('Edge/');
    if (edge > 0) {
        return parseInt(ua.substring(edge + 5, ua.indexOf('.', edge)), 10);
    }
    return false;
}

// Find the best regression formula for the data set
function regressionFit(data) {
    var bestRegression;
    var bestR2 = NaN;
    _.forEach([
        regression.linear(data),
        regression.exponential(data),
        regression.logarithmic(data),
        regression.power(data),
        regression.polynomial(data)
    ], function(result) {
        if(isNaN(bestR2) || (!isNaN(result.r2) && result.r2 > bestR2)) {
            bestRegression = result;
            bestR2 = result.r2;
        }
    });
    return bestRegression;
}
