#include "main.h"
#include <Wire.h>
#include <SPI.h>

#include "frser.h"
#include "spihw_teensyspi.h"


uint8_t rawhidRequest[DAP_PACKET_SIZE];
uint8_t rawhidResponse[DAP_PACKET_SIZE];


struct interrupt_notifier {
  bool active = false; 
  unsigned long last_update = 0; 
  volatile uint32_t isr_count[CORE_NUM_INTERRUPT] = {}; 
  volatile uint32_t handler_count[CORE_NUM_INTERRUPT] = {}; 
};

interrupt_notifier pin_interrupt_state; 

#define FRSER_TERM 8
#define FRSER_TERM2 9
#define INTERRUPT_HANDLER_DEF(N) \
void interrupt_handler_##N(void) { \
  ++pin_interrupt_state.isr_count[ N ]; \
} 

INTERRUPT_HANDLER_DEF(0)
INTERRUPT_HANDLER_DEF(1)
INTERRUPT_HANDLER_DEF(2)
INTERRUPT_HANDLER_DEF(3)
INTERRUPT_HANDLER_DEF(4)
INTERRUPT_HANDLER_DEF(5)
INTERRUPT_HANDLER_DEF(6)
INTERRUPT_HANDLER_DEF(7)
INTERRUPT_HANDLER_DEF(8)
INTERRUPT_HANDLER_DEF(9)
INTERRUPT_HANDLER_DEF(10)
INTERRUPT_HANDLER_DEF(11)
INTERRUPT_HANDLER_DEF(12)
INTERRUPT_HANDLER_DEF(13)
INTERRUPT_HANDLER_DEF(14)
INTERRUPT_HANDLER_DEF(15)
INTERRUPT_HANDLER_DEF(16)
INTERRUPT_HANDLER_DEF(17)
INTERRUPT_HANDLER_DEF(18)
INTERRUPT_HANDLER_DEF(19)
INTERRUPT_HANDLER_DEF(20)
INTERRUPT_HANDLER_DEF(21)
INTERRUPT_HANDLER_DEF(22)
INTERRUPT_HANDLER_DEF(23)
INTERRUPT_HANDLER_DEF(24)
INTERRUPT_HANDLER_DEF(25)
INTERRUPT_HANDLER_DEF(26)
INTERRUPT_HANDLER_DEF(27)
INTERRUPT_HANDLER_DEF(28)
INTERRUPT_HANDLER_DEF(29)
INTERRUPT_HANDLER_DEF(30)
INTERRUPT_HANDLER_DEF(31)
INTERRUPT_HANDLER_DEF(32)
INTERRUPT_HANDLER_DEF(33)
#if defined(ARDUINO_TEENSY41) || defined(ARDUINO_TEENSY40) || defined(ARDUINO_TEENSY36)
INTERRUPT_HANDLER_DEF(34)
INTERRUPT_HANDLER_DEF(35)
INTERRUPT_HANDLER_DEF(36)
INTERRUPT_HANDLER_DEF(37)
INTERRUPT_HANDLER_DEF(38)
INTERRUPT_HANDLER_DEF(39)
#endif
#if defined(ARDUINO_TEENSY41) || defined(ARDUINO_TEENSY36)
INTERRUPT_HANDLER_DEF(40)
INTERRUPT_HANDLER_DEF(41)
INTERRUPT_HANDLER_DEF(42)
INTERRUPT_HANDLER_DEF(43)
INTERRUPT_HANDLER_DEF(44)
INTERRUPT_HANDLER_DEF(45)
INTERRUPT_HANDLER_DEF(46)
INTERRUPT_HANDLER_DEF(47)
INTERRUPT_HANDLER_DEF(48)
INTERRUPT_HANDLER_DEF(49)
INTERRUPT_HANDLER_DEF(50)
INTERRUPT_HANDLER_DEF(51)
INTERRUPT_HANDLER_DEF(52)
INTERRUPT_HANDLER_DEF(53)
INTERRUPT_HANDLER_DEF(54)
#endif

#if defined(ARDUINO_TEENSY36)
INTERRUPT_HANDLER_DEF(55)
INTERRUPT_HANDLER_DEF(56)
INTERRUPT_HANDLER_DEF(57)
INTERRUPT_HANDLER_DEF(58)
INTERRUPT_HANDLER_DEF(59)
INTERRUPT_HANDLER_DEF(60)
INTERRUPT_HANDLER_DEF(61)
INTERRUPT_HANDLER_DEF(62)
INTERRUPT_HANDLER_DEF(63)
#endif 
#if defined(ARDUINO_TEENSY31)
static_assert(CORE_NUM_INTERRUPT == 34, "interrupt handler length does not match processor");
#elif defined(ARDUINO_TEENSY40)
static_assert(CORE_NUM_INTERRUPT == 40, "interrupt handler length does not match processor 40");
#elif defined(ARDUINO_TEENSY41)
static_assert(CORE_NUM_INTERRUPT == 55, "interrupt handler length does not match processor for 36 or 41");

# elif defined(ARDUINO_TEENSY36)
static_assert(CORE_NUM_INTERRUPT == 64, "interrupt handler length does not match processor for 36 or 41");

#endif

#define INTERRUPT_HANDLER(N) \
interrupt_handler_##N


#define REGISTER_PIN_INTERRUPT(N) \
  case N: \
     attachInterrupt(digitalPinToInterrupt(N), INTERRUPT_HANDLER(N), CHANGE); \
     break



#define INA260_DEFAULT_ADDR 0x40
#define MFG_ID 0xFE
#define DIE_ID 0xFF
#define DIE_ID 0xFF
#define INA260_CONFIG 0x00
#define INA260_CURRENT 0x01
#define INA260_BUSVOLTAGE 0x02
#define INA260_POWER 0x03
struct ina260config {
  int continuious = 0;
  int address = INA260_DEFAULT_ADDR;
  unsigned long last_update = 0; 
}ina260config_t; 
void printina230(auto dev);

CLI_COMMAND(resetFunc);
CLI_COMMAND(termFunc);
CLI_COMMAND(powerFunc);
CLI_COMMAND(swdFunc);
CLI_COMMAND(serialFunc);
CLI_COMMAND(pinFunc);
CLI_COMMAND(anaFunc);
CLI_COMMAND(helpFunc);
CLI_COMMAND(bootloaderFunc);
CLI_COMMAND(i2cFunc);

CLI_COMMAND(interruptFunc);
CLI_COMMAND(interruptdisFunc);

CLI_COMMAND(ina260Func);



void setup() {

#ifdef ARDUINO_TEENSY40
  pinMode(1, INPUT);
  pinMode(26, INPUT);
  pinMode(27, INPUT);
  pinMode(28, INPUT);
  pinMode(29, INPUT);
#endif

  pinMode(SPI_WP, INPUT);
  pinMode(SPI_MOSI, INPUT);
  pinMode(SPI_MISO, INPUT);
  pinMode(SPI_SCK, INPUT);
  pinMode(SPI_CS, INPUT);


  pinMode(BUTTON_HOST_POWER, OUTPUT_OPENDRAIN);
  digitalWrite(BUTTON_HOST_POWER, HIGH);
  //orb seems to have no pullup on reset circuit
  //pinMode(BUTTON_HOST_RESET, INPUT);
  pinMode(BUTTON_HOST_RESET, OUTPUT_OPENDRAIN);
  digitalWrite(BUTTON_HOST_RESET, HIGH);
  ARM_DWT_CTRL |= ARM_DWT_CTRL_CYCCNTENA;

  Serial.begin(115200);

#ifdef ARDUINO_TEENSY40
  //Serial1.setTX(0);
  Serial1.setRX(0);
#endif

  Serial1.begin(115200);
#ifdef ARDUINO_TEENSY40
  pinMode(1, INPUT);
  pinMode(26, INPUT);
  pinMode(27, INPUT);
  pinMode(28, INPUT);
  pinMode(29, INPUT);
#endif
  Serial2.begin(115200);

  Serial3.begin(115200);
  pinMode(1, INPUT);


  // put your setup code here, to run once:
  //RawHID.begin(rawhidRequest, DAP_PACKET_SIZE);
  CLI.setDefaultPrompt("> ");
  CLI.addCommand("reset", resetFunc);
  CLI.addCommand("term", termFunc);
  CLI.addCommand("power", powerFunc);
  CLI.addCommand("swd", swdFunc);

  CLI.addCommand("serial", serialFunc);
  CLI.addCommand("pin", pinFunc);
  CLI.addCommand("ana", anaFunc);
  CLI.addCommand("help", helpFunc);
  CLI.addCommand("?", helpFunc);
  CLI.addCommand("bootloader", bootloaderFunc);

  CLI.addCommand("i2c", i2cFunc);
  CLI.addCommand("int", interruptFunc);
  CLI.addCommand("intd", interruptdisFunc);

  CLI.addCommand("ina260", ina260Func);


  CLI.addClient(Serial);

  Wire.begin();

  DAP_Setup();

#ifdef ARDUINO_TEENSY40
  pinMode(1, INPUT_PULLDOWN);
  pinMode(26, INPUT_PULLDOWN);
  pinMode(27, INPUT_PULLDOWN);
  pinMode(28, INPUT_PULLDOWN);
  pinMode(29, INPUT_PULLDOWN);
#endif
}

#if defined(ARDUINO_TEENSY31) || defined(ARDUINO_TEENSY36)
#define DEFAULT_HW_TERM_1 1
#define DEFAULT_HW_TERM_2 2
#elif defined(ARDUINO_TEENSY40) || defined (ARDUINO_TEENSY41)
#define DEFAULT_HW_TERM_1 2
#define DEFAULT_HW_TERM_2 1
#endif

//terminal 0 is command, 1 is redirect all to hw port 1, 2 is port 2, etc. 
int current_terminal_1 = DEFAULT_HW_TERM_1; 
int current_terminal_2 = DEFAULT_HW_TERM_2; 
uint32_t term1_baud = 0; 
uint32_t term2_baud = 0; 

HardwareSerial * getPort(int portnumber)
{
    switch (portnumber) {
      case 1:
        return &Serial1;
        break;
      case 2:
        return &Serial2;
        break;
      case 3:
        return &Serial3;
        break;
#if defined(ARDUINO_TEENSY41) || defined(ARDUINO_TEENSY40)
      case 4:
        return &Serial4;
        break;
      case 5:
        return &Serial5;
        break;
      case 6:
        return &Serial6;
        break;
#endif
      default: 
        return NULL;
    }

}

void handle_serial(){
  static const int serial_rx_loop_max = 128; 
  int serial_rx_count = 0; 
  HardwareSerial * hw = NULL;
  CLI.process();

  if (SerialUSB1.baud() != term1_baud){
    term1_baud = SerialUSB1.baud(); 
    Serial.print("USB Term 1 Baud set to ");
    Serial.println(term1_baud);
    hw = getPort(current_terminal_1);
    if (hw)
      hw->begin(term1_baud);
  }

  if (SerialUSB2.baud() != term2_baud){
    term2_baud = SerialUSB2.baud();
    Serial.print("USB Term 2 Baud set to ");
    Serial.println(term2_baud);
    hw = getPort(current_terminal_2);
    if (hw)
      hw->begin(term2_baud);
  }


  hw = getPort(current_terminal_1);
  if (hw) {
    while(SerialUSB1.available() > 0) {

        hw->write(SerialUSB1.read());
    }
    while(hw->available()) {
      SerialUSB1.write(hw->read());
      if (serial_rx_count++ > serial_rx_loop_max) break; 
    }

  }

  hw = getPort(current_terminal_2);
  if (hw) {
    while(SerialUSB2.available() > 0) {
        hw->write(SerialUSB2.read());
    }
    while(hw->available()) {
      SerialUSB2.write(hw->read());
      if (serial_rx_count++ > serial_rx_loop_max) break; 
    }
  } else {
    if (current_terminal_2 == FRSER_TERM || current_terminal_2 == FRSER_TERM2) {
      while(SerialUSB2.available() > 0) {
        frser_operation(SerialUSB2.read());
      }
    }
  }
}
//#define DAP_DEBUG

void loop() {
  // put your main code here, to run repeatedly:
  //

  handle_serial();

  auto bytesAvailable = RawHID.recv(rawhidRequest, 0);
  if (bytesAvailable > 0) {

    #ifdef DAP_DEBUG
    Serial.print("dap ");
    Serial.print(rawhidRequest[0], HEX);
    Serial.print(" ");
    Serial.print(rawhidRequest[1], HEX);
    Serial.print(" ");
    #endif /* DAP_DEBUG */

    auto sz = DAP_ProcessCommand(rawhidRequest, rawhidResponse);
    
    #ifdef DAP_DEBUG
    Serial.print("rsp ");
    Serial.print(sz, HEX);
    Serial.println(" B");
    #endif /* DAP_DEBUG */
    
    if (sz > 0) {
      RawHID.send(rawhidResponse, 100);
    }
  }
  //only print interrupt status updates max 10hz
  if (pin_interrupt_state.active && millis() > (pin_interrupt_state.last_update + 100)){
    pin_interrupt_state.last_update = millis();
    for (size_t i = 0; i < CORE_NUM_INTERRUPT; i++){
        if (pin_interrupt_state.isr_count[i] != pin_interrupt_state.handler_count[i]){
          Serial.print("pin ");
          Serial.print(i);
          Serial.print(" changed ");
          Serial.print(pin_interrupt_state.isr_count[i] - pin_interrupt_state.handler_count[i]);
          Serial.println(" times");
          pin_interrupt_state.handler_count[i] = pin_interrupt_state.isr_count[i]; 
        }
    }
  }

  /* Print power readings */
  if (ina260config_t.continuious != 0 && (millis() > (ina260config_t.last_update + ina260config_t.continuious))) {
    ina260config_t.last_update = millis();
    printina230(&Serial);
  }

}


CLI_COMMAND(resetFunc) {
    pinMode(BUTTON_HOST_RESET, OUTPUT_OPENDRAIN);
    digitalWrite(BUTTON_HOST_RESET, LOW);
    delay(500);
    digitalWrite(BUTTON_HOST_RESET, HIGH);
    pinMode(BUTTON_HOST_RESET, INPUT);
    dev->println("reset complete");

    return 0;
}


CLI_COMMAND(powerFunc) {
    pinMode(BUTTON_HOST_POWER, OUTPUT_OPENDRAIN);
    digitalWrite(BUTTON_HOST_POWER, LOW);
    delay(1000);
    digitalWrite(BUTTON_HOST_POWER, HIGH);
    dev->println("power complete");

    return 0;
}

CLI_COMMAND(termFunc) {
    if (argc != 3) {
        dev->print("Usage: term vcpid(1,2) id(1=hw port 1, 2=hw port 2 ... N=hw port N | ");
        
        dev->print(FRSER_TERM);
        dev->print("=flashrom) ");
#ifdef ARDUINO_TEENSY41
        dev->print(FRSER_TERM2);
        dev->print("=flashrom (Teensy4.1 onboard QSPI header))");
#endif
        dev->println();
        return 10;
    }
    int term = atoi(argv[2]);
    int usb_term = atoi(argv[1]);
    if (usb_term == 1){
      current_terminal_1 = term;
      term1_baud = 0; 
      dev->print("ACM1 Set to HW Uart ");
      dev->println(term);

    }else if (usb_term == 2){
      if (current_terminal_2 != term && current_terminal_2 == FRSER_TERM) {
        dev->println("Disabling frser spi pins");
        //make sure flashrom pins are disabled (spi)
        pinMode(SPI_WP, INPUT);
        pinMode(SPI_MOSI, INPUT);
        pinMode(SPI_MISO, INPUT);
        pinMode(SPI_SCK, INPUT);
        pinMode(SPI_CS, INPUT);
#ifdef ARDUINO_TEENSY40
        pinMode(SPI1_DO, INPUT);
        pinMode(SPI1_DI, INPUT);
        pinMode(SPI1_SCK, INPUT);
        pinMode(SPI1_CS, INPUT);
#endif
      }
      current_terminal_2 = term;
      term2_baud = 0; 
      if (term == FRSER_TERM){ 
        spi_set_port(0);
        frser_init();
      }
      if (term == FRSER_TERM2) {
        spi_set_port(1);
        frser_init();
      }

      dev->print("ACM2 Set to ");
      switch(term){
        case 1: 
          dev->println("HW Uart 1");
          break; 
        case 2: 
          dev->println("HW Uart 2");
          break; 
        case 3: 
          dev->println("HW Uart 3");
          break; 
        case 4: 
          dev->println("HW Uart 4");
          break; 
        case 5: 
          dev->println("HW Uart 5");
          break; 
        case 6: 
          dev->println("HW Uart 6");
          break; 
        case FRSER_TERM: 
          dev->println("Serprog");
          break; 
        case FRSER_TERM2: 
          dev->println("Serprog Teensy Onboard Flash Header");
          break; 
        default: 
          dev->println("Invalid");
          break;
      }

    }else{
      dev->println("Invalid usb terminal id ");
    }

    return 0;
}

CLI_COMMAND(swdFunc) {
    if ((argc != 4) || (argc != 6) ) {
        dev->println("Usage: swd swclk swdio nRESET [tdi tdo]");
        dev->println("Current Pin settings:");
        dev->print("\tswclk:");
        dev->println(pin_swclk);
        dev->print("\tswdio:");
        dev->println(pin_swdio);
        dev->print("\tnRESET:");
        dev->println(pin_nreset);
        dev->print("\ttdi:");
        dev->println(pin_tdi);
        dev->print("\ttdo:");
        dev->println(pin_tdo);
        return 10;
    }
    //set all old values to input disabled: 
    pinMode(pin_swclk, INPUT);
    pinMode(pin_swdio, INPUT);
    pinMode(pin_nreset, INPUT);
    pinMode(pin_tdi, INPUT);
    pinMode(pin_tdo, INPUT);

    pin_swclk = atoi(argv[1]);
    pin_swdio = atoi(argv[2]);
    pin_nreset = atoi(argv[3]);
    if (argc == 6) {
      pin_tdi = atoi(argv[4]); 
      pin_tdo = atoi(argv[5]); 
      dev->println("tdi/tdo pins set\n");
    }
    DAP_SETUP(); 
    dev->println("swd pins set\n");

    return 0;
}


CLI_COMMAND(serialFunc) {
  if (argc < 3) {
      dev->println("Usage: serial port baud [txpin rxpin]");
      return 10;
  }
  int port = atoi(argv[1]);
  int baudrate = atoi(argv[2]);
  int txpin = -1; 
  int rxpin = -1; 
  HardwareSerial * hw = NULL;


  hw = getPort(port);
  if (hw) {
    hw->begin(baudrate); 

    dev->print("serial baud set to:");
    dev->print(baudrate);

    if (argc == 5) {
      txpin= atoi(argv[3]);
      rxpin = atoi(argv[4]);

      hw->setTX(txpin); 
      hw->setRX(rxpin); 

      dev->print(" serial pin set TX:");
      dev->print(txpin);
      dev->print(" RX:");
      dev->print(rxpin);
    }

  } else {
    dev->println("Invalid port");
    return 10;
  }

  dev->println();

  return 0;
}

CLI_COMMAND(anaFunc) {
    if (argc != 2) {
        dev->println("Usage: ana pin");
        return 10;
    }
    int pin = atoi(argv[1]);
    dev->print("pin ");
    dev->print(pin);
    dev->print("=");
    dev->println(analogRead(pin));
    

    return 0;
}

CLI_COMMAND(pinFunc) {
    if (argc < 2) {
        dev->println("Usage: pin pin 1|0 [in,inup,indown,out,opendrain]");
        for (int i=0; i<34; i++){
          dev->print("pin");
          dev->print(i);
          dev->print("\t=");
          dev->println((digitalRead(i) == HIGH) ? 1 : 0);

        }
        return 10;
    }
    int pin = atoi(argv[1]);

    
    dev->print("pin ");
    dev->print(pin);
    dev->print(" ");
    if (argc >= 4) {
      if (strcmp("disable",argv[3]) == 0){
        pinMode(pin, INPUT_DISABLE);
        dev->print("disabled ");
      }
      if (strcmp("in",argv[3]) == 0){
        pinMode(pin, INPUT);
        dev->print("input ");
      }
      if (strcmp("inup",argv[3]) == 0){
        pinMode(pin, INPUT_PULLUP);
        dev->print("input pullup ");
      }
      if (strcmp("indown",argv[3]) == 0){
        pinMode(pin, INPUT_PULLDOWN);
        dev->print("input pulldown ");

      }
      if (strcmp("out",argv[3]) == 0){
        pinMode(pin, OUTPUT);
        dev->print("output ");

      }
      if (strcmp("opendrain",argv[3]) == 0){
        pinMode(pin, OUTPUT_OPENDRAIN);
        dev->print("output opendrain ");

      }
    }
    if (argc >= 3) {
      int state = atoi(argv[2]);
      dev->print("set to ");
      dev->print(state);
      dev->print(" ");

      digitalWrite(pin, (state == 1) ? HIGH: LOW );
    }
    if (argc >= 2) {
      dev->print("=");
      dev->println((digitalRead(pin) == HIGH) ? 1 : 0);
    }

    return 0;
}

CLI_COMMAND(helpFunc) {
    dev->println("reset - toggle reset (pin 17) open drain");
    dev->println("power - toggle power (pin 16) open drain");
    dev->println("term vcpid(1,2) id(1=hw port 1, 2=hw port 2, 3=hw port 3 4=flashrom)");
    dev->println("serial port baud [txpin rxpin]");
    dev->println("ana pin");
    dev->println("   pin 15 - read analog value of pin 15");

    dev->println("pin pin 1|0 [in,inup,indown,out,opendrain]");
    dev->println("   pin 10 - read digital value of pin 10");
    dev->println("   pin 10 1 out- Drive pin 10 high, set output");

    dev->println("int[d] pin - enable or [d]isable notifications of pin change interrupt");

    dev->println("i2c - perform i2c [r]ead [w]rite operations");
    dev->println("   i2c addr [w] hex_bytes [r] number of bytes");
    dev->println("   i2c clk frequency_hz");
    dev->println("   note you can string a sequence of reads/writes together:");
    dev->println("   i2c 10 w 0 r 2 will write 0, then read 2 bytes");

    dev->println("swd swclk swdio nRESET [tdi tdo]");
    return 0;
}

CLI_COMMAND(bootloaderFunc) {

#if defined(ARDUINO_TEENSY31) || defined(ARDUINO_TEENSY36)
    _reboot_Teensyduino_();
#else
  asm("bkpt #251");
#endif
    return 0;
}
#define CMD_MODE_IDLE 0
#define CMD_MODE_READ 1
#define CMD_MODE_WRITE 2

void print_i2c_status(auto dev, int status){
  switch(status){
    case 0: 
    break; 
    case 1: 
        dev->println("I2C Data too long");
    break; 
    case 2: 
        dev->println("I2C NAK On address");
    break;  
    case 3: 
        dev->println("I2C NAK on data");
    break;  
    default: 
        dev->println("I2C Unknown error");
  }
}
CLI_COMMAND(i2cFunc) {
    int success = 0; 
    if (argc < 2) {
      int error = 0; 
      dev->println("Usage: i2c addr [w] hex_bytes [r] number of bytes");
      dev->println("Usage: i2c clk frequency_hz");

      dev->println("Devices");
      for (int hdr=0; hdr<0xf; hdr++){
        dev->print(hdr,HEX);
        dev->print("\t");
      }
      dev->println();
      for (int address=0; address<0x7f; address++){
        Wire.beginTransmission(address);
        error = Wire.endTransmission();
        if (error == 0) {
          dev->print(address,HEX);
          dev->print("\t");
        }
        else{
          dev->print("--\t");
        }
        if ((address % 0x0f) == 0x0e){
          dev->println();
        }
      }
      dev->println();
      return 10;
    }

    if (argc == 3){
      if (strcmp("clk",argv[1]) == 0){
        int speed = atoi(argv[2]);
        Wire.setClock(speed);
        dev->print("I2C Clock set to ");
        dev->print(speed);
        dev->println("Hz");
      }
    }
    uint8_t address = strtol(argv[1], 0, 16); 
    int cmd_mode = CMD_MODE_READ; 
    for(int cmd = 2; cmd < argc; cmd++){
      if (strcmp("r",argv[cmd]) == 0){
        if (cmd_mode == CMD_MODE_WRITE){
          success = Wire.endTransmission(false); 
          print_i2c_status(dev, success);
        }
        cmd_mode = CMD_MODE_READ;
        if (cmd+1 < argc){
            int num_bytes = Wire.requestFrom(address, strtol(argv[cmd+1], 0, 16));
            while(Wire.available()){
              dev->print(Wire.read(), HEX);
              dev->print(" ");
            }
        }
        else {
          dev->println("Invalid i2c r, missing number of bytes to read"); 
          return 10;
        }
        cmd++; 
      }
      else if (strcmp("w",argv[cmd]) == 0){
        if (cmd_mode == CMD_MODE_WRITE){
          success = Wire.endTransmission(true); //send cached data
          print_i2c_status(dev, success);
        }
        Wire.beginTransmission(address);
        cmd_mode = CMD_MODE_WRITE; 
      }
      else {
        uint8_t data = strtol(argv[cmd], 0, 16); 
        if (cmd_mode == CMD_MODE_WRITE){
          Wire.write(data); 
        }
        else { 
          dev->print(argv[cmd]); 
          dev->println(" - invalid command data"); 
        }
      }
    }
    if (cmd_mode == CMD_MODE_WRITE){
      success = Wire.endTransmission(); //send cached data
      print_i2c_status(dev, success);
    }
    dev->println();
    return 0;
}


CLI_COMMAND(interruptFunc) {
    if (argc != 2) {
        dev->println("Usage: int pin");
        return 10;
    }
    int pin = atoi(argv[1]);
    switch(pin){
      REGISTER_PIN_INTERRUPT(0);
      REGISTER_PIN_INTERRUPT(1);
      REGISTER_PIN_INTERRUPT(2);
      REGISTER_PIN_INTERRUPT(3);
      REGISTER_PIN_INTERRUPT(4);
      REGISTER_PIN_INTERRUPT(5);
      REGISTER_PIN_INTERRUPT(6);
      REGISTER_PIN_INTERRUPT(7);
      REGISTER_PIN_INTERRUPT(8);
      REGISTER_PIN_INTERRUPT(9);
      REGISTER_PIN_INTERRUPT(10);
      REGISTER_PIN_INTERRUPT(11);
      REGISTER_PIN_INTERRUPT(12);
      REGISTER_PIN_INTERRUPT(13);
      REGISTER_PIN_INTERRUPT(14);
      REGISTER_PIN_INTERRUPT(15);
      REGISTER_PIN_INTERRUPT(16);
      REGISTER_PIN_INTERRUPT(17);
      REGISTER_PIN_INTERRUPT(18);
      REGISTER_PIN_INTERRUPT(19);
      REGISTER_PIN_INTERRUPT(20);
      REGISTER_PIN_INTERRUPT(21);
      REGISTER_PIN_INTERRUPT(22);
      REGISTER_PIN_INTERRUPT(23);
      REGISTER_PIN_INTERRUPT(24);
      REGISTER_PIN_INTERRUPT(25);
      REGISTER_PIN_INTERRUPT(26);
      REGISTER_PIN_INTERRUPT(27);
      REGISTER_PIN_INTERRUPT(28);
      REGISTER_PIN_INTERRUPT(29);
      REGISTER_PIN_INTERRUPT(30);
      REGISTER_PIN_INTERRUPT(31);
      REGISTER_PIN_INTERRUPT(32);
      REGISTER_PIN_INTERRUPT(33);
    }
    dev->print("Registering pin change notification on ");
    dev->println(pin);
    pin_interrupt_state.active = true; 
    return 0;
}


CLI_COMMAND(interruptdisFunc) {
    if (argc != 2) {
        dev->println("Usage: intd pin");
        return 10;
    }
    int pin = atoi(argv[1]);
    detachInterrupt(digitalPinToInterrupt(pin));
    dev->print("Unregistering pin change notification on ");
    dev->println(pin);
    return 0;
}

int ina260reg(int address, int reg, int writeVal = -1) {
  uint32_t result = 0;
  int success = 0;
  Wire.beginTransmission(address);
  Wire.write(reg); 
  if (writeVal != -1) {
    Wire.write((writeVal >> 8) & 0xFF);
    Wire.write(writeVal & 0xFF);
  }
  success = Wire.endTransmission(writeVal != -1); 
  print_i2c_status(&Serial, success);
  if (writeVal == -1) {
    int num_bytes = Wire.requestFrom(address, 2);
    while(Wire.available()){
      result = (result << 8) + Wire.read();
    }
    success = Wire.endTransmission(true); 
    print_i2c_status(&Serial, success);

  }
  return result;
}

void printina230(auto dev) {
  int ret = 0;
  float voltage = 0;
  float current = 0;
  float power = 0;
  voltage = ina260reg(ina260config_t.address, INA260_BUSVOLTAGE);
  voltage *= 1.25;

  current = ina260reg(ina260config_t.address, INA260_CURRENT);
  current *= 1.25;

  power = ina260reg(ina260config_t.address, INA260_POWER);
  power *= 10;

  dev->print("ina260 Voltage:\t");
  dev->print(voltage);
  dev->print("\tCurrent:\t");
  dev->print(current);
  dev->print("\tPower:\t");
  dev->println(power);
}

CLI_COMMAND(ina260Func) {
  int ret = 0;
  if (argc < 2) {
    dev->println("Usage: ina260 i2caddr ");

  }
  uint8_t address = strtol(argv[1], NULL, 16);
  ina260config_t.address = address;
  ret = ina260reg(address, MFG_ID);
  if (ret != 0x5449) {
    dev->println("Did not detect INA260");
  }
  printina230(dev);
  if (argc >= 3) {
    ina260config_t.continuious = strtol(argv[2], NULL, 0);
  }

  return 0;
}
